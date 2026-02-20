"""
Daily Embedding Sync Lambda

Automatically embeds new Webex chat files to S3 Vectors.
Designed to run daily via EventBridge scheduler.

Features:
- Smart conversation-based chunking (thread detection, topics)
- Processes only new files (since last run)
- Tracks last processed date in SSM Parameter Store
- Supports multi-project usage
- Prepares metadata for future feedback system
"""

import boto3
import json
import logging
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from smart_chunker import chunkByConversation

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client('s3')
s3vectors = boto3.client('s3vectors')
bedrock = boto3.client('bedrock-runtime')
ssm = boto3.client('ssm')


# =============================================================================
# Configuration
# =============================================================================

def getConfig():
    """Get configuration from environment variables."""
    return {
        'source_bucket': os.environ.get('CHAT_DATA_S3_BUCKET'),
        'vector_bucket': os.environ.get('VECTOR_BUCKET'),
        'index_name': os.environ.get('VECTOR_INDEX'),
        'project_id': os.environ.get('PROJECT_ID', 'ccoe-chat-history'),
        'ssm_prefix': os.environ.get('SSM_PREFIX', '/embedding-sync'),
        'max_workers': int(os.environ.get('MAX_WORKERS', '10')),
        'batch_size': int(os.environ.get('BATCH_SIZE', '50'))
    }


# =============================================================================
# State Management (Track Last Processed Date via SSM Parameter Store)
# =============================================================================

def getSsmParameterName(ssm_prefix, project_id):
    """Build SSM parameter name for a project."""
    return f"{ssm_prefix}/{project_id}/last-processed-date"


def getLastProcessedDate(ssm_prefix, project_id):
    """Get the last processed date from SSM Parameter Store."""
    param_name = getSsmParameterName(ssm_prefix, project_id)
    try:
        response = ssm.get_parameter(Name=param_name)
        return response['Parameter']['Value']
    except ssm.exceptions.ParameterNotFound:
        logger.info(f"Parameter {param_name} not found - first run")
        return None
    except Exception as e:
        logger.error(f"Could not get last processed date: {e}")
        return None


def setLastProcessedDate(ssm_prefix, project_id, date_str):
    """Update the last processed date in SSM Parameter Store."""
    param_name = getSsmParameterName(ssm_prefix, project_id)
    try:
        ssm.put_parameter(
            Name=param_name,
            Value=date_str,
            Type='String',
            Overwrite=True,
            Description=f"Last processed date for {project_id} embedding sync"
        )
        logger.info(f"Updated {param_name} to {date_str}")
    except Exception as e:
        logger.error(f"Could not update last processed date: {e}")


# =============================================================================
# Core Embedding Functions
# =============================================================================

def getEmbedding(text, model_id='amazon.titan-embed-text-v2:0'):
    """Generate embedding vector using Amazon Bedrock."""
    response = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({'inputText': text})
    )
    result = json.loads(response['body'].read())
    return result['embedding']


def getEmbeddingsParallel(texts, max_workers=10):
    """Generate embeddings in parallel."""
    results = [None] * len(texts)
    
    def embedSingle(index, text):
        try:
            embedding = getEmbedding(text)
            return {'index': index, 'embedding': embedding, 'error': None}
        except Exception as e:
            return {'index': index, 'embedding': None, 'error': str(e)}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(embedSingle, i, text): i 
            for i, text in enumerate(texts)
        }
        for future in as_completed(futures):
            result = future.result()
            results[result['index']] = result
    
    return results


def storeVectorsBatch(bucket_name, index_name, vectors, batch_size=50):
    """Store vectors in batches."""
    total_stored = 0
    errors = []
    
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i:i + batch_size]
        vector_data_list = []
        
        for v in batch:
            vector_data = {
                'key': v['key'],
                'data': {'float32': v['embedding']}
            }
            if v.get('metadata'):
                vector_data['metadata'] = v['metadata']
            vector_data_list.append(vector_data)
        
        try:
            s3vectors.put_vectors(
                vectorBucketName=bucket_name,
                indexName=index_name,
                vectors=vector_data_list
            )
            total_stored += len(batch)
        except Exception as e:
            logger.error(f"Error storing batch {i}: {str(e)}")
            errors.append({'batch_start': i, 'error': str(e)})
    
    return {'stored': total_stored, 'errors': errors if errors else None}


# =============================================================================
# S3 Data Loading
# =============================================================================

def getNewChatFiles(bucket_name, prefix, since_date=None):
    """Get list of chat files, optionally filtered by date."""
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
    
    files = []
    for page in pages:
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.endswith('_chat.json'):
                continue
            
            # Extract date from filename (format: {roomId}_{date}_chat.json)
            filename = key.split('/')[-1]
            parts = filename.rsplit('_', 2)
            if len(parts) >= 2:
                file_date = parts[-2]  # Get date part
                
                # Filter by date: only process files AFTER the last processed date
                if since_date and file_date <= since_date:
                    continue
                
                files.append({
                    'key': key,
                    'room_id': parts[0],
                    'date': file_date,
                    'last_modified': obj['LastModified']
                })
    
    return files


def loadAndTransformMessages(bucket_name, file_info):
    """Load a single chat file and transform to expected format."""
    try:
        file_obj = s3.get_object(Bucket=bucket_name, Key=file_info['key'])
        messages = json.loads(file_obj['Body'].read().decode('utf-8'))
        
        transformed = []
        for msg in messages:
            if not msg.get('text'):
                continue
            
            transformed.append({
                'timestamp': msg.get('created'),
                'sender': msg.get('personEmail', msg.get('personDisplayName', 'Unknown')),
                'text': msg.get('text', ''),
                'room_id': file_info['room_id'],
                'message_id': msg.get('id')
            })
        
        return transformed
    except Exception as e:
        logger.error(f"Error loading {file_info['key']}: {e}")
        return []


# =============================================================================
# Main Processing
# =============================================================================

def processNewFiles(config, files, context=None):
    """Process new chat files and embed to S3 Vectors using smart chunking.
    
    Saves progress after each file so that if the Lambda times out,
    the next invocation resumes from where it left off.
    """
    results = {
        'files_processed': 0,
        'vectors_stored': 0,
        'errors': []
    }
    
    # Sort files by date so we can checkpoint incrementally
    files_sorted = sorted(files, key=lambda f: f.get('date', ''))
    
    for file_info in files_sorted:
        # Check remaining execution time - stop early if running low
        # Reserve 30s for cleanup and SSM write
        if context and hasattr(context, 'get_remaining_time_in_millis'):
            remaining_ms = context.get_remaining_time_in_millis()
            if remaining_ms < 30_000:
                logger.info(f"Only {remaining_ms}ms remaining - stopping early to save progress")
                break
        
        try:
            logger.info(f"Processing: {file_info['key']}")
            
            # Load messages
            messages = loadAndTransformMessages(config['source_bucket'], file_info)
            if not messages:
                continue
            
            # Deduplicate
            seen_ids = set()
            unique_messages = []
            for msg in messages:
                msg_id = msg.get('message_id')
                if msg_id and msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    unique_messages.append(msg)
                elif not msg_id:
                    unique_messages.append(msg)
            
            # Smart conversation chunking (uses defaults: 30 min gap, 50 messages, 4000 chars)
            chunks = chunkByConversation(unique_messages, file_info['room_id'])
            if not chunks:
                continue
            
            # Generate embeddings in parallel
            texts = [chunk['text'] for chunk in chunks]
            embedding_results = getEmbeddingsParallel(texts, config['max_workers'])
            
            # Prepare vectors with metadata from smart chunker
            vectors_to_store = []
            for i, (chunk, emb_result) in enumerate(zip(chunks, embedding_results)):
                if emb_result['error']:
                    results['errors'].append({
                        'file': file_info['key'],
                        'chunk_id': chunk['chunk_id'],
                        'error': emb_result['error']
                    })
                    continue
                
                # Use metadata from smart chunker, add project_id and source
                metadata = chunk['metadata'].copy()
                metadata['project_id'] = config['project_id']
                metadata['source'] = 'webex'
                
                # Remove None values — S3 Vectors only accepts strings, numbers, booleans, arrays
                sanitized_metadata = {k: v for k, v in metadata.items() if v is not None}
                
                vectors_to_store.append({
                    'key': chunk['chunk_id'],
                    'embedding': emb_result['embedding'],
                    'metadata': sanitized_metadata
                })
            
            # Store vectors
            if vectors_to_store:
                store_result = storeVectorsBatch(
                    config['vector_bucket'],
                    config['index_name'],
                    vectors_to_store,
                    config['batch_size']
                )
                results['vectors_stored'] += store_result['stored']
                if store_result['errors']:
                    results['errors'].extend(store_result['errors'])
            
            results['files_processed'] += 1
            logger.info(f"  -> Stored {len(vectors_to_store)} vectors")
            
            # Checkpoint: save progress after each file so we don't
            # reprocess everything if the Lambda times out
            setLastProcessedDate(
                config['ssm_prefix'],
                config['project_id'],
                file_info['date']
            )
            
        except Exception as e:
            results['errors'].append({
                'file': file_info['key'],
                'error': str(e)
            })
    
    return results


# =============================================================================
# Lambda Handler
# =============================================================================

def handler(event, context):
    """
    Lambda handler for daily embedding sync.
    
    Triggered by EventBridge scheduler (daily).
    Processes new Webex chat files using smart conversation chunking.
    """
    logger.info("Starting daily embedding sync with smart chunking")
    
    try:
        # Get configuration
        config = getConfig()
        
        # Validate config
        if not all([config['source_bucket'], config['vector_bucket'], config['index_name']]):
            raise ValueError(
                "Missing required environment variables: "
                "CHAT_DATA_S3_BUCKET, VECTOR_BUCKET, VECTOR_INDEX"
            )
        
        logger.info(f"Config: source={config['source_bucket']}, "
                    f"vector={config['vector_bucket']}, "
                    f"project={config['project_id']}")
        
        # Get last processed date from SSM Parameter Store
        last_date = getLastProcessedDate(config['ssm_prefix'], config['project_id'])
        if last_date:
            logger.info(f"Processing files since: {last_date}")
        else:
            # First run - process all files (no date filter)
            logger.info("First run - processing all available files")
        
        # Get new files
        new_files = getNewChatFiles(
            config['source_bucket'],
            "feed/",
            since_date=last_date
        )
        
        if not new_files:
            logger.info("No new files to process")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No new files', 'files_processed': 0})
            }
        
        logger.info(f"Found {len(new_files)} new files to process")
        
        # Process files with smart chunking
        # Pass context so we can check remaining time and stop early if needed
        results = processNewFiles(config, new_files, context=context)
        
        logger.info(f"Sync complete: {results['files_processed']} files, "
                    f"{results['vectors_stored']} vectors")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Sync complete',
                'files_processed': results['files_processed'],
                'vectors_stored': results['vectors_stored'],
                'errors': len(results['errors']) if results['errors'] else 0
            })
        }
        
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# =============================================================================
# Local Testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Validate required environment variables
    if not os.environ.get('CHAT_DATA_S3_BUCKET'):
        print("Set CHAT_DATA_S3_BUCKET environment variable")
        sys.exit(1)
    
    print("Running daily embedding sync with smart conversation chunking...")
    result = handler({}, None)
    print(json.dumps(result, indent=2))
