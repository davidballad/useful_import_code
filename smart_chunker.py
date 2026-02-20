"""
Smart Chat Chunker

Conversation-aware chunking for chat history embeddings.
Groups messages by conversation threads and detects resolution.
"""

from datetime import datetime, timedelta
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Resolution words that indicate a thread is complete
RESOLUTION_WORDS = [
    'thanks', 'thank you', 'thx', 'ty',
    'solved', 'resolved', 'fixed', 'working now',
    'got it', 'that worked', 'perfect', 'awesome',
    'appreciate it', 'makes sense', 'understood',
    'all set', 'good to go', 'sorted',
    'closing this', 'issue resolved', 'problem solved'
]

# Topic keywords for classification
TOPIC_KEYWORDS = {
    'vpn': ['vpn', 'network', 'connection', 'proxy', 'tunnel', 'zscaler'],
    'terraform': ['terraform', 'tf', 'module', 'provider', 'state', 'tfvars'],
    'iam': ['iam', 'role', 'policy', 'permission', 'access', 'saml', 'federation'],
    'aws': ['aws', 'amazon', 's3', 'ec2', 'lambda', 'cloudwatch', 'bedrock'],
    'deployment': ['deploy', 'pipeline', 'cicd', 'jenkins', 'github', 'actions'],
    'troubleshooting': ['error', 'failed', 'issue', 'problem', 'help', 'fix', 'broken'],
    'security': ['security', 'encrypt', 'kms', 'secrets', 'credential', 'token'],
    'cost': ['cost', 'billing', 'finops', 'budget', 'spend', 'savings']
}


def detectResolution(text):
    """Check if text contains resolution words indicating thread completion."""
    text_lower = text.lower()
    for word in RESOLUTION_WORDS:
        if word in text_lower:
            return True
    return False


def detectTopics(text):
    """Detect topics from conversation text using keyword matching."""
    text_lower = text.lower()
    detected = []
    
    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                detected.append(topic)
                break
    
    return detected if detected else ['general']


def getPrimaryTopic(topics):
    """Get the most relevant topic (first non-general)."""
    for topic in topics:
        if topic != 'general':
            return topic
    return 'general'


def parseTimestamp(ts):
    """Parse timestamp string to datetime object."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        ts = ts.replace('Z', '+00:00')
        if '.' in ts:
            ts = ts.split('.')[0] + '+00:00'
        try:
            return datetime.fromisoformat(ts)
        except:
            return datetime.now()
    return datetime.now()



def chunkByConversation(messages, channel_id, gap_minutes=30, max_messages=50, max_chars=4000):
    """
    Smart conversation-based chunking.
    
    Groups messages by:
    1. Time gaps (30+ min = new conversation)
    2. Resolution detection (thanks/solved = end of thread)
    3. Size limits (max messages/chars per chunk)
    """
    if not messages:
        return []
    
    sorted_messages = sorted(messages, key=lambda x: x.get('timestamp', ''))
    
    chunks = []
    current_chunk = []
    current_chars = 0
    last_timestamp = None
    chunk_index = 0
    
    for msg in sorted_messages:
        ts = parseTimestamp(msg.get('timestamp', ''))
        msg_text = f"[{msg.get('sender', 'Unknown')}]: {msg.get('text', '')}"
        
        should_split = False
        
        # Time gap detection
        if last_timestamp:
            gap = (ts - last_timestamp).total_seconds() / 60
            if gap > gap_minutes:
                should_split = True
        
        # Size limits
        if len(current_chunk) >= max_messages:
            should_split = True
        if current_chars + len(msg_text) > max_chars:
            should_split = True
        
        # Resolution detection
        if current_chunk:
            last_msg_text = current_chunk[-1].get('text', '')
            if detectResolution(last_msg_text):
                if '?' in msg.get('text', '') or (last_timestamp and (ts - last_timestamp).total_seconds() / 60 > 10):
                    should_split = True
        
        # Split if needed
        if should_split and current_chunk:
            chunk = createChunk(current_chunk, channel_id, chunk_index)
            chunks.append(chunk)
            current_chunk = []
            current_chars = 0
            chunk_index += 1
        
        current_chunk.append(msg)
        current_chars += len(msg_text)
        last_timestamp = ts
    
    # Last chunk
    if current_chunk:
        chunk = createChunk(current_chunk, channel_id, chunk_index)
        chunks.append(chunk)
    
    return chunks


def createChunk(messages, channel_id, index):
    """Create a chunk with full metadata from messages."""
    if not messages:
        return None
    
    start_time = messages[0].get('timestamp', '')
    end_time = messages[-1].get('timestamp', '')
    
    # Format conversation text
    text_parts = []
    for msg in messages:
        sender = msg.get('sender', 'Unknown')
        text = msg.get('text', '')
        text_parts.append(f"[{sender}]: {text}")
    
    chunk_text = '\n'.join(text_parts)
    
    # Detect topics
    topics = detectTopics(chunk_text)
    primary_topic = getPrimaryTopic(topics)
    
    # Check if thread is complete
    is_complete = False
    for msg in messages[-3:]:
        if detectResolution(msg.get('text', '')):
            is_complete = True
            break
    
    # Generate chunk_id
    chunk_date = str(start_time).split('T')[0] if 'T' in str(start_time) else str(start_time)[:10]
    chunk_id = f"{channel_id}-{chunk_date}-{index}"
    
    return {
        'chunk_id': chunk_id,
        'text': chunk_text,
        'metadata': {
            'type': 'chat_history',
            'channel_id': channel_id,
            'timestamp': chunk_date,
            'topics': topics,
            'primary_topic': primary_topic,
            'is_thread_complete': is_complete,
            'is_verified': False,
            'priority': 0,
            'start_time': str(start_time),
            'end_time': str(end_time),
            'message_count': len(messages),
            'chunk_text': chunk_text[:2000],
            'corrects_vector_key': None,
            'original_question': None,
            'verified_answer': None
        }
    }


def addTopicKeywords(topic, keywords):
    """Add new keywords to an existing topic."""
    if topic in TOPIC_KEYWORDS:
        TOPIC_KEYWORDS[topic].extend(keywords)
    else:
        TOPIC_KEYWORDS[topic] = keywords


def getTopicKeywords():
    """Get current topic keywords configuration."""
    return TOPIC_KEYWORDS.copy()
