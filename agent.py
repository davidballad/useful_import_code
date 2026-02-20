import hashlib
import hmac
import json
import os
import boto3
import requests
from datetime import datetime, timezone, timedelta
import logging
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

streamable_http_mcp_client = MCPClient(lambda: streamablehttp_client("https://rrplxr7nwk.execute-api.us-east-1.amazonaws.com/prod"))

# Agent is now used within MCP context in each function that needs it
    



botToken = os.environ['BOT_TOKEN']
# webhook_secret = os.environ['WEBHOOK_SECRET']
confluence_token = os.environ['CONFLUENCE_TOKEN']
ai_gateway_api = os.environ['AIGATEWAY_API']
current_okta_token = os.environ['CURRENT_OKTA_TOKEN']
current_okta_expiry = os.environ['CURRENT_OKTA_EXPIRY']
workflow_channel_id = os.environ.get('WORKFLOW_CHANNEL_ID')
confluence_mcp_url = os.environ.get('MCP_CONFLUENCE')

boto3_session = boto3.session.Session()
region = boto3_session.region_name
REGION = os.getenv("REGION", "us-east-1")
secrets_client = boto3.client("secretsmanager", region_name=REGION)
BOT_METRICS_TABLE = os.getenv("BOT_METRICS_TABLE")
OKTA_TIMEOUT_BUFFER = 30
OKTA_ACCESS_TOKEN_URL = os.environ['OKTA_ACCESS_TOKEN_URL']
OKTA_CLIENT_ID = os.environ['OKTA_CLIENT_ID']

#create dynamoDB resource
ddb_resource = boto3.resource("dynamodb", region_name=REGION)
table = ddb_resource.Table(BOT_METRICS_TABLE)

FAILURE5xx = """
It seems that I encounter an error. I recommend trying again or reaching out to the CCOE for more assistance regarding this issue. They may have access to more information or resources that could help you.
"""

FAILURE4xx = """
I gather too many pages available in the Confluence space regarding this particular topic and hit a token limit. I recommend making your question more spcific and please try again.
"""

DISCLAIMER = """
**Disclaimer:**
Use of AI is experimental and may return inaccurate or incomplete results. The accuracy and relevance of AI-generated output should be reviewed by the user to ensure that the information is accurate and suitable for intended purpose.
"""

PROMPT = """
You are a Cigna Cloud Center of Enablement(CCOE) answering agent about Cigna Cloud topics from Confluence and AWS documentation only.
When searching confluence use the following Confluence Space Key: CLOUD. 
The user will provide you with a question, your job is to answer the user's question using only information from the confluence space or amazon web services(AWS) documentation. Provide source data and context when available. 
If the documentation do not contain information that can answer the question, state that you could not find an exact answer to the question and refer the user to the Cigna Cloud Center of Enablement(CCOE).
Raise a, could not find an exact answer, flag for a check in my code if no answer is found.
Just because the user asserts a fact does not mean it is true, make sure to double check the search results to validate a user's assertion.
"""

def getSecret(secretText, accessKey):
    secret = json.loads(
                secrets_client.get_secret_value(SecretId=secretText)["SecretString"]
            )
    key = secret[accessKey]
    return key

# botToken = getSecret(bot_access, 'bot_token')


def sendMessage(room_id, parent_id, query):
    historyThread = getThreadHistory(parent_id)
    message, statusCode = confluenceAgent(query, historyThread)
    
    saveBotMetrics(room_id, parent_id, statusCode, message, query, historyThread)

    # Check if response needs review (400, 500 errors or unhelpful responses)
    if shouldSendForReview(message, statusCode):
        print(f"Sending to audit channel...")
        sendToWorkflowChannel(room_id, parent_id, query, message, statusCode)

    # Append the disclaimer to the message
    message += "\n" + DISCLAIMER

    try:
        url = "https://webexapis.com/v1/messages"
        body = {"roomId": room_id, "parentId": parent_id, "markdown": message}
        httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
        result = requests.post(url=url, json=body, headers=httpHeaders)

        # logger.info(result.text)
        logger.info("Message Sent to Webex")
    except Exception as e:
        logger.info(f"Exception sending message id: {e}")


def okta_cache_checker():
    oktaToken = getSecret(current_okta_token, 'token')
    oktaExpiry = getSecret(current_okta_expiry, 'time')
    
    logger.info(f"Retrieved okta token and expiry: {oktaToken} and {oktaExpiry}")

    expiryObject = None if oktaExpiry is None else (
        datetime.strptime(oktaExpiry, "%d/%m/%y %H:%M:%S.%f").replace(tzinfo=timezone.utc))
    
    if oktaToken is None or oktaExpiry is None or datetime.now(timezone.utc) > expiryObject:
        newToken, expiresIn = okta_auth()
        currentTime = datetime.now(timezone.utc)
        expiryTime = currentTime + timedelta(seconds=expiresIn - OKTA_TIMEOUT_BUFFER)
        expiryTimeStr = expiryTime.strftime("%d/%m/%y %H:%M:%S.%f")
        
        secrets_client.update_secret(
            SecretId=current_okta_token,
            Description="Okta JWT token to access AI Gateway",
            SecretString="{{\"token\": \"{}\"}}".format(newToken),
        )
        secrets_client.update_secret(
            SecretId=current_okta_expiry,
            Description="Okta JWT token expiry",
            SecretString="{{\"time\": \"{}\"}}".format(expiryTimeStr),
        )

        logger.info("Updated Current Okta token and expiry.")

        return newToken, expiryTimeStr
    return oktaToken, oktaExpiry


def okta_auth():
    access_token_url = OKTA_ACCESS_TOKEN_URL
    client_id = OKTA_CLIENT_ID
    client_secret = getSecret(ai_gateway_api, 'api_key')

    try:
        token_req_payload = {'grant_type': 'client_credentials', 'scope' : 'ent'}

        token_response = requests.post(access_token_url , data = token_req_payload, allow_redirects = False, auth = (client_id, client_secret))

        if token_response.status_code != 200:
            print(f"TOKEN_RES: {token_response.status_code}")
            logger.info(f"Failed to obtain token from OAuth2 server {token_response.text}")
        else:
            tokens = json.loads(token_response.text)
        return tokens['access_token'], tokens['expires_in']
    except Exception as e:
        logger.info(f"Failed to obtained a new token: {e}")


def confluenceAgent(query, historyThread):
    modelId = 'ai-coe-gpt41-nano:analyze'
    confluenceToken = getSecret(confluence_token, 'token')
    oktaAuth, oktaExpiry = okta_cache_checker()
    
    prompt = f"Use this confluence token:{confluenceToken} {PROMPT}"
    
    try:
        url = "https://aigateway-prod.apps-1.gp-1-prod.openshift.cignacloud.com/api/v1/copilot/AI10514_CCOE_ChatBot/" + modelId + '/agent/chat'
        payload = {
            "messages": [
                {
                "role": "system",
                "content": prompt
                },
                {
                "role": "assistant",
                "content": historyThread
                },
                {
                "role": "user",
                "content": query
                }
            ],
            "top_p": 0.25,
            "temperature": 0.7,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "max_tokens": 100
        }
        httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + oktaAuth }
        request = requests.post(url, headers=httpHeaders, json=payload)
        
        if request.status_code == 200:
            return request.text, request.status_code
        elif request.status_code == 400:
            logger.info(f"Confluence Agent 4xx Exception: {request.text}")
            return FAILURE4xx, request.status_code
        else:
            logger.info(f"Confluence Agent 5xx Exception: {request.text}")
            raise Exception(FAILURE5xx)
        
    except Exception as e:
        logger.info(f"Confluence Agent Exception: {e}")


def saveBotMetrics(room_id, parent_id, statusCode, message, userQuery, historyThread):
    current_time = str(datetime.now())
    historyThread+=f"User: {userQuery}\nAssistant: {message}\n"
    expire_at = int((datetime.now() + timedelta(days=7)).timestamp())

    try:
        result = table.update_item(
            Key={
                'parentId': parent_id,
            },
            UpdateExpression="set statusCode=:s, roomId=:i, requestTime=:d, messageThreat=:m, expireAt=:x",
            ExpressionAttributeValues={
                ':s': statusCode,
                ':i': room_id,
                ':d': current_time,
                ':m': historyThread,
                ':x': expire_at
            },
        )
        
        logger.info(f"Bot metrics saved")
    except Exception as e:
        logger.info(f"Error saving bot metrics: {e}")


def getThreadHistory(parent_id):
    try:
        response = table.get_item(
            Key={
                "parentId": parent_id,
            },
        )
                
        if 'Item' in response:
            return response['Item']['messageThreat']
        else:
            return ""
    except Exception as e:
        logger.info(f"Error reading from DynamoDB: {e}")


def getBotMetricsData(parent_id):
    """Get complete bot metrics data from DynamoDB for a thread"""
    try:
        response = table.get_item(
            Key={
                "parentId": parent_id,
            },
        )
                
        if 'Item' in response:
            item = response['Item']
            
            # Parse the message thread to extract the original question and bot response
            message_thread = item.get('messageThreat', '')
            status_code = item.get('statusCode', 0)
            room_id = item.get('roomId', '')
            request_time = item.get('requestTime', '')
            
            # Extract the most recent user question and bot response
            lines = message_thread.split('\n')
            user_question = ""
            bot_response = ""
            
            for i, line in enumerate(lines):
                if line.startswith('User: '):
                    user_question = line[6:]  # Remove "User: " prefix
                elif line.startswith('Assistant: '):
                    bot_response = line[11:]  # Remove "Assistant: " prefix
            
            return {
                'original_question': user_question,
                'bot_response': bot_response,
                'full_thread': message_thread,
                'status_code': status_code,
                'room_id': room_id,
                'request_time': request_time,
                'thread_id': parent_id
            }
        else:
            return None
    except Exception as e:
        logger.info(f"Error reading bot metrics from DynamoDB: {e}")
        return None


def shouldSendForReview(message, statusCode):
    """Check if response should be sent to workflow channel for review"""
    print(f"Checking....shouldSendForReview function")
    if statusCode == 400 or statusCode == 500:
        return True
    
    # Check for common unhelpful response patterns
    unhelpful_indicators = [
        "could not find an exact answer",
        "refer the user to the Cigna Cloud Center of Enablement",
        "reaching out to the CCOE",
        "I recommend trying again"
    ]
    
    message_lower = message.lower()
    print(f"MSG_TO_CHECK: {message_lower}")
    re = any(indicator in message_lower for indicator in unhelpful_indicators)
    print(f"CHECKER.. {re}")
    return re


def sendToWorkflowChannel(original_room_id, parent_id, query, response, statusCode):
    """Send problematic responses to workflow channel for review"""
    if not workflow_channel_id:
        logger.info("No workflow channel configured")
        return
    
    try:
        review_message = f"""
**Response Review Needed** 🔍

**Original Question:** {query}

**Bot Response:** {response}

**Status Code:** {statusCode}

**Original Room:** {original_room_id}
**Thread ID:** {parent_id}

*React with 👍 if this response needs a Confluence page update*
        """
        
        url = "https://webexapis.com/v1/messages"
        body = {"roomId": workflow_channel_id, "markdown": review_message}
        httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
        result = requests.post(url=url, json=body, headers=httpHeaders)
        
        logger.info("Review message sent to workflow channel")
    except Exception as e:
        logger.info(f"Exception sending to workflow channel: {e}")


def handleReaction(event_data):
    """Handle thumbs up reactions to suggest Confluence page updates"""
    try:
        # Extract reaction details
        message_id = event_data['data']['messageId']
        reaction = event_data['data'].get('reaction')
        print(f"Reaction: {reaction}. MessageID: {message_id}")
        
        if reaction != '👍':
            return
        
        # Get the original message to extract thread ID
        url = f"https://webexapis.com/v1/messages/{message_id}"
        print(f"URL:: {url}")
        httpHeaders = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken}
        print(f"httpHeaders:: {httpHeaders}")
        response = requests.get(url=url, headers=httpHeaders)
        print(f"response:: {response}")
        
        if response.status_code == 200:
            message_data = response.json()
            message_text = message_data.get('markdown', '')
            # print(f"MessageDetails: {message_data}")
            print(f"MessageText: {message_text}")

        #     # Extract thread ID from the review message
            thread_id = None
            if "**Thread ID:**" in message_text:
                for line in message_text.split('\n'):
                    if "**Thread ID:**" in line:
                        thread_id = line.split("**Thread ID:**")[1].strip()
                        print(f"Thread ID: {thread_id}")
                        break
            
            if thread_id:
                # Get the original question and context from DynamoDB
                original_data = getBotMetricsData(thread_id)
                # print(f"OriginalData: {original_data}")
                if original_data:
                    print("Suggesting pages...")
                    suggestConfluenceUpdate(original_data, message_id)
                else:
                    logger.info(f"No metrics data found for thread ID: {thread_id}")
            else:
                logger.info("Could not extract thread ID from review message")
        
    except Exception as e:
        logger.info(f"Exception handling reaction: {e}")


def suggestConfluenceUpdate(original_data, review_message_id):
    """Use Confluence MCP to suggest which page should be updated"""
    try:
        
        if not original_data:
            logger.info("No original data provided")
            return
        
        query = original_data['original_question']
        bot_response = original_data['bot_response']
        full_thread = original_data['full_thread']
        
        # Search for relevant pages using the MCP Agent within context
        print(f"Searching Confluence for: {query}")
        with streamable_http_mcp_client:
            tools = streamable_http_mcp_client.list_tools_sync()
            agent = Agent(tools=tools)
            search_result = agent(f"Search for pages related to: {query} in CLOUD space, limit 5 results, no follow up questions.")
            search_content = str(search_result)
        print(f"Search Successful: {search_content}")
        
        # Create intelligent suggestion message with agent's formatted results
        suggestion_message = f"""
**Confluence Update Suggestion** 📝

**Original Question:** {query}

**Bot's Response:** {bot_response[:200]}{'...' if len(bot_response) > 200 else ''}

**Relevant Pages Found:**
{search_content}

**Thread ID:** {original_data['thread_id']}
**Status Code:** {original_data['status_code']}

**Recommended Action:** Review the pages above and reply if you want to update any page with missing information.
        """
        
        # Send suggestion to workflow channel
        url = "https://webexapis.com/v1/messages"
        body = {"roomId": workflow_channel_id, "markdown": suggestion_message}
        httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
        result = requests.post(url=url, json=body, headers=httpHeaders)
        print(f"Res2:: {result}")
        
        logger.info("Confluence update suggestion sent with MCP search results")
        
    except Exception as e:
        logger.info(f"Exception suggesting Confluence update: {e}")
        # Fallback to basic suggestion
        try:
            query = original_data.get('original_question', 'Unknown') if original_data else 'Unknown'
            bot_response = original_data.get('bot_response', 'Unknown') if original_data else 'Unknown'
            thread_id = original_data.get('thread_id', 'Unknown') if original_data else 'Unknown'
            
            fallback_message = f"""
**Confluence Update Suggestion 4** 📝

**Original Question:** {query}

**Bot's Response:** {bot_response[:200]}{'...' if len(bot_response) > 200 else ''}

**Error:** Unable to search Confluence automatically ({str(e)})

**Thread ID:** {thread_id}

**Manual Action Required:** Please search the CLOUD space manually for relevant pages to update.
            """
            
            url = "https://webexapis.com/v1/messages"
            body = {"roomId": workflow_channel_id, "parentId": review_message_id, "markdown": fallback_message}
            httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
            requests.post(url=url, json=body, headers=httpHeaders)
        except:
            pass


def performConfluenceUpdate(parent_text, parent_message_id):
    """Handle 'Proceed with update' requests using agent"""
    try:
        # Use agent to extract the update details from the analysis and execute
        with streamable_http_mcp_client:
            tools = streamable_http_mcp_client.list_tools_sync()
            agent = Agent(tools=tools)
            
            # Ask agent to extract update details and perform the update
            # update_prompt = f"""
            # Based on this Confluence update analysis message, extract the specific page and content to update:
            
            # {parent_text}
            
            # Then perform the actual Confluence page update. Extract:
            # 1. The specific page title to update
            # 2. The content that should be added/updated
            # 3. Execute the update with appropriate version comment
            
            # Provide a summary of what was updated.
            # """
            
            update_prompt = f"""
            # Based on this Confluence update analysis message, extract the specific page and content to update:
            
            {parent_text}
            Caution: Do not change the actual page that is suggested in the analysis, instead perform the update in a test page only, Page ID: 1516196418
            1. The specific page title to update
            2. The content that should be added/updated
            3. Execute the update with appropriate version comment
            
            Provide a brief summary of what was updated.
            """
            
            update_result = agent(update_prompt)
            update_text = str(update_result)
            
            # For now, just print the update (as requested)
            print(f"CONFLUENCE UPDATE EXECUTED: {update_text}")
            
            # Send confirmation to user
            confirmation_message = f"""
**✅ Confluence Update Completed!**

{update_text}

*Note: This is currently in test mode - the actual update has been logged for review.*
            """
            
            url = "https://webexapis.com/v1/messages"
            body = {"roomId": workflow_channel_id, "markdown": confirmation_message}
            httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
            requests.post(url=url, json=body, headers=httpHeaders)
            
            return True
            
    except Exception as e:
        logger.info(f"Exception handling proceed with update: {e}")
        return False


def handleConfluenceUpdateRequest(parent_message_id, update_content):
    """Handle requests to update Confluence pages with intelligent agent assistance"""
    try:
        # Get the parent message to see if it's a Confluence suggestion
        url = f"https://webexapis.com/v1/messages/{parent_message_id}"
        httpHeaders = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken}
        response = requests.get(url=url, headers=httpHeaders)
        
        if response.status_code != 200:
            return False
            
        parent_message = response.json()
        parent_text = parent_message.get('markdown', '')
        
        # Check if this is a Confluence suggestion message
        if "Confluence Update Suggestion" not in parent_text:
            print(f"Update Suggestions not found")
            return False
        
        # Look for update commands in the reply
        update_content_lower = update_content.lower()
        
        # Check if user wants to proceed with a previously analyzed update
        if "proceed with update" in update_content_lower:
            # Handle the proceed case - extract info from parent message and execute update
            return performConfluenceUpdate(parent_text, parent_message_id)
        
        # Check for initial update requests
        if not any(cmd in update_content_lower for cmd in ['update page', 'add to page', 'update confluence']):
            print(f"Update Content message not found")
            return False
        
        # Use agent to intelligently handle the update request
        with streamable_http_mcp_client:
            tools = streamable_http_mcp_client.list_tools_sync()
            agent = Agent(tools=tools)
            
            # Ask agent to analyze the update request and provide comprehensive overview
            analysis_prompt = f"""
            Analyze this Confluence update request:
            
            **Original Suggestion Message:**
            {parent_text}
            
            **User's Update Request:**
            {update_content}
            
            Please provide:
            1. Which specific page should be updated (if user specified one, use it; if not, suggest the most appropriate page from the search results)
            2. What content should be added/updated and why
            3. A comprehensive overview of the proposed changes
            4. Justification for why this page is the best choice
            
            Format your response as a clear recommendation for the user to review.
            """
            
            analysis_result = agent(analysis_prompt)
            analysis_text = str(analysis_result)
            
            # Send comprehensive analysis to user
            response_message = f"""
**Confluence Update Analysis** 📋

{analysis_text}

**Next Steps:**
Reply with "Proceed with update" to execute the changes, or provide additional instructions.

*Note: For now, this will print a confirmation message instead of actually updating the page.*
            """
            
            url = "https://webexapis.com/v1/messages"
            body = {"roomId": workflow_channel_id, "markdown": response_message}
            httpHeaders = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken }
            requests.post(url=url, json=body, headers=httpHeaders)
            
            # For now, just print the update action (as requested)
            print(f"UPDATE ACTION: Would update Confluence page based on agent analysis: {analysis_text[:200]}...")
            
            return True
        
    except Exception as e:
        logger.info(f"Exception handling Confluence update request: {e}")
        return False



def handler(event, context):
    # print(f"*** INITIAL_EVENT: {event}****")
    # key = getSecret(webhook_secret, 'webex_genai_webhook' )

    # raw = event['body']
    # xSparkSignature = event['headers']['X-Spark-Signature']
    # hashed = hmac.new(key.encode(), raw.encode(), hashlib.sha1)
    # validatedSignature = hashed.hexdigest()

    match = True

    if match:
        logger.info("__Valid Request__")

        response = json.loads(event['body'])
        event_type = response.get('resource')
        logger.info(f"EVENT_TYPE: {event_type}")
        # Handle reaction events
        if event_type == 'attachmentActions':
            handleReaction(response)
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Reaction processed'})
            }
        
        # Handle message events
        message_id = response['data']['id']
        try:
            url = "https://webexapis.com/v1/messages/" + message_id
            httpHeaders = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + botToken}
            request = requests.get(url=url, headers=httpHeaders)
            result = request.json()
            print(f"result: {result}")
            query = result['text']
            room_id = result['roomId']
            
            # Check if this is a reply to a Confluence suggestion (in workflow channel)
            if room_id == workflow_channel_id and 'parentId' in result:
                print("***WorkflowChannel***")
                parent_id = result['parentId']
                # Check if parent message is a Confluence suggestion
                if handleConfluenceUpdateRequest(parent_id, query):
                    return {
                        'statusCode': 200,
                        'body': json.dumps({'message': 'Confluence update processed'})
                    }
            
            # Regular bot query processing
            query = query.partition(' ')[2]
    
            if 'parentId' in result:
                parentId = result['parentId']
            else:
                parentId = message_id
            

            # logger.info(f"Sending Message: {query}")
            sendMessage(room_id, parentId, query)
            return {
                'statusCode': 200,
                'body': json.dumps(response, sort_keys=True, indent=4)
            }
        except Exception as e:
            logger.info(f"Exception getting message id: {e}")
            
    else:
        logger.info("Secret does not match. Authentication Failed!")




def main():
    # Test function locally
    test_event = {
        "body": json.dumps({"id":"Y2lzY29zcGFyazovL3VzL1dFQkhPT0svM2JlYWM0YjAtMTc4Mi00YzA3LTk5MDgtNWNhZjBmODA5MWUyy",
                 "messageId":"Y2lzY29zcGFyazovL3VzL01FU1NBR0UvYTNkM2ZlYTAtOThmZS0xMWYwLWI4Y2ItYjE2YWQ2NWM0NjMy",
                 "reaction": "👍",
                  "name":"Confluence Workflow Test",
                  "targetUrl":"https://lc8x56cjab.execute-api.us-east-1.amazonaws.com/dev/messages","resource":"message","event":"created",
                  "filter":"mentionedPeople=Y2lzY29zcGFyazovL3VzL1BFT1BMRS82MDIxM2IwZS0wYWYzLTRkNDgtOTQ5YS0xOTg3OTUxYzUzNGM",
                  "orgId":"Y2lzY29zcGFyazovL3VzL09SR0FOSVpBVElPTi9jMjMxNDcyMi00YzRiLTRiNTYtYjNhMy1lYjA5NDhlMTQzNjM",
                  "createdBy":"Y2lzY29zcGFyazovL3VzL1BFT1BMRS82MDIxM2IwZS0wYWYzLTRkNDgtOTQ5YS0xOTg3OTUxYzUzNGM",
                  "appId":"Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OL0MzMmM4MDc3NDBjNmU3ZGYxMWRhZjE2ZjIyOGRmNjI4YmJjYTQ5YmE1MmZlY2JiMmM3ZDUxNWNiNGEwY2M5MWFh","ownedBy":"creator","status":"active","created":"2025-09-10T18:54:44.262Z","actorId":"Y2lzY29zcGFyazovL3VzL1BFT1BMRS83NzUwZTE4Ny1kZTkwLTQ2M2EtYWZiNC1lZjY4NjBhMmIwYzE",
                  "data":{"id":"Y2lzY29zcGFyazovL3VzL01FU1NBR0UvMDAwY2JkNTAtOTkwMC0xMWYwLThiYTctMmY3ZmM5ZmU1NTg0",
                          "roomId":"Y2lzY29zcGFyazovL3VzL1JPT00vNWQ1NjIzMTAtODg3Ni0xMWYwLTg5ZGEtNDkxNGYxYTQxNzY5",
                          "roomType":"group",
                          "messageId":"Y2lzY29zcGFyazovL3VzL01FU1NBR0UvYTNkM2ZlYTAtOThmZS0xMWYwLWI4Y2ItYjE2YWQ2NWM0NjMy",
                          "reaction": "👍",
                          "personId":"Y2lzY29zcGFyazovL3VzL1BFT1BMRS83NzUwZTE4Ny1kZTkwLTQ2M2EtYWZiNC1lZjY4NjBhMmIwYzE",
                          "personEmail":"David.Balladares@evernorth.com",
                          "mentionedPeople":["Y2lzY29zcGFyazovL3VzL1BFT1BMRS82MDIxM2IwZS0wYWYzLTRkNDgtOTQ5YS0xOTg3OTUxYzUzNGM"],
                          "created":"2025-09-12T00:19:51.727Z"}})}
    ###STEP 2
    # result = handleReaction(test_event['body'])
    ###STEP 3
    result = handler(test_event, "context")
    print(f"Result: {result}")

if __name__ == "__main__":
    main()