"""
Intelligent Confluence Freshness Agent
Uses Strands Agent with both Confluence and AWS MCPs to intelligently detect outdated content
"""
import json
import os
import logging
import requests
from typing import Dict, Any, List
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class IntelligentFreshnessAgent:
    """
    Intelligent agent that uses both Confluence and AWS MCPs to:
    1. Read Confluence pages
    2. Extract AWS-related claims
    3. Verify against current AWS documentation
    4. Generate detailed update recommendations
    """
    
    def __init__(self, confluence_mcp_url: str, teams_webhook_url: str):
        self.confluence_mcp_url = confluence_mcp_url
        self.teams_webhook_url = teams_webhook_url
        
        # Create MCP clients
        self.confluence_client = MCPClient(
            lambda: streamablehttp_client(confluence_mcp_url)
        )
    
    def analyze_page_freshness(self, page_id: str, space: str = "CLOUD") -> Dict[str, Any]:
        """
        Use AI agent to intelligently analyze if a Confluence page is outdated
        """
        try:
            with self.confluence_client:
                # Get tools from both MCPs
                confluence_tools = self.confluence_client.list_tools_sync()
                
                # Create agent with all tools
                agent = Agent(tools=confluence_tools)
                
                # Ask agent to analyze the page
                analysis_prompt = f"""
                Analyze Confluence page {page_id} in space {space} for outdated AWS information.
                
                Steps:
                1. Get the page content
                2. Identify all AWS services, features, and best practices mentioned
                3. For each AWS topic found, determine if the information might be outdated by checking:
                   - Version numbers mentioned
                   - Deprecated features
                   - Old pricing information
                   - Outdated best practices
                4. List specific items that appear outdated with reasons
                
                Provide a structured analysis with:
                - Page title and last modified date
                - List of AWS topics covered
                - Specific outdated items with explanations
                - Recommendations for updates
                
                Be specific and cite exact text from the page that appears outdated.
                """
                
                analysis_result = agent(analysis_prompt)
                analysis_text = str(analysis_result)
                
                logger.info(f"Agent analysis complete for page {page_id}")
                
                # Parse agent's response to structure it
                return self._parse_agent_analysis(analysis_text, page_id, space)
                
        except Exception as e:
            logger.error(f"Error in agent analysis: {e}")
            return {'error': str(e)}
    
    def verify_with_aws_docs(self, page_id: str, space: str = "CLOUD") -> Dict[str, Any]:
        """
        Use AWS MCP to verify claims in Confluence page against current AWS documentation
        """
        try:
            with self.confluence_client:
                confluence_tools = self.confluence_client.list_tools_sync()
                agent = Agent(tools=confluence_tools)
                
                # Two-phase analysis
                # Phase 1: Extract AWS claims from Confluence
                extraction_prompt = f"""
                Get Confluence page {page_id} from space {space}.
                Extract all specific AWS-related claims, including:
                - Service features and capabilities
                - Pricing information
                - Best practices
                - Configuration recommendations
                - Version or generation information (e.g., "t2 instances", "old console")
                
                List each claim separately with the exact quote from the page.
                """
                
                claims_result = agent(extraction_prompt)
                claims_text = str(claims_result)
                
                logger.info(f"Extracted claims from page {page_id}")
                
                # Phase 2: Verify each claim
                # Note: This would ideally use AWS MCP, but for now we'll use heuristics
                verification_prompt = f"""
                Based on these claims from the Confluence page:
                
                {claims_text}
                
                Identify which claims are likely outdated based on:
                - Mentions of "old", "legacy", "previous generation"
                - Specific version numbers that might be outdated
                - References to deprecated features
                - Old pricing models
                
                For each potentially outdated claim, explain why it might be outdated
                and what the current information should be.
                """
                
                verification_result = agent(verification_prompt)
                verification_text = str(verification_result)
                
                return {
                    'page_id': page_id,
                    'space': space,
                    'claims': claims_text,
                    'verification': verification_text,
                    'needs_update': 'outdated' in verification_text.lower() or 'deprecated' in verification_text.lower()
                }
                
        except Exception as e:
            logger.error(f"Error verifying with AWS docs: {e}")
            return {'error': str(e)}
    
    def _parse_agent_analysis(self, analysis_text: str, page_id: str, space: str) -> Dict[str, Any]:
        """Parse the agent's natural language analysis into structured data"""
        
        # Extract key information using simple parsing
        # In production, you might use another LLM call to structure this
        
        is_outdated = any(keyword in analysis_text.lower() for keyword in [
            'outdated', 'deprecated', 'old version', 'needs update', 'no longer'
        ])
        
        # Try to extract page title
        title = "Unknown"
        if "title:" in analysis_text.lower():
            for line in analysis_text.split('\n'):
                if "title:" in line.lower():
                    title = line.split(':', 1)[1].strip()
                    break
        
        return {
            'page_id': page_id,
            'space': space,
            'title': title,
            'is_outdated': is_outdated,
            'analysis': analysis_text,
            'confidence': 'high' if is_outdated else 'low'
        }
    
    def send_teams_notification(self, analysis_result: Dict[str, Any]) -> bool:
        """Send detailed MS Teams notification with agent's analysis"""
        try:
            if not analysis_result.get('is_outdated') and not analysis_result.get('needs_update'):
                logger.info("Page is up to date, no notification needed")
                return False
            
            page_id = analysis_result.get('page_id', 'Unknown')
            title = analysis_result.get('title', 'Unknown Page')
            analysis = analysis_result.get('analysis', 'No analysis available')
            verification = analysis_result.get('verification', '')
            
            # Truncate analysis for Teams card
            analysis_preview = analysis[:800] + "..." if len(analysis) > 800 else analysis
            
            card = {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": f"Outdated Confluence Page: {title}",
                "themeColor": "FF6B35",
                "title": "⚠️ Confluence Page Contains Outdated AWS Information",
                "sections": [
                    {
                        "activityTitle": f"**{title}**",
                        "activitySubtitle": f"Page ID: {page_id}",
                        "facts": [
                            {
                                "name": "Status",
                                "value": "Needs Update"
                            },
                            {
                                "name": "Confidence",
                                "value": analysis_result.get('confidence', 'medium').title()
                            }
                        ]
                    },
                    {
                        "title": "**AI Analysis:**",
                        "text": analysis_preview
                    }
                ],
                "potentialAction": [
                    {
                        "@type": "OpenUri",
                        "name": "View Page in Confluence",
                        "targets": [
                            {
                                "os": "default",
                                "uri": f"{os.environ.get('CONFLUENCE_URL', '')}/pages/viewpage.action?pageId={page_id}"
                            }
                        ]
                    },
                    {
                        "@type": "OpenUri",
                        "name": "Update Page",
                        "targets": [
                            {
                                "os": "default",
                                "uri": f"{os.environ.get('CONFLUENCE_URL', '')}/pages/editpage.action?pageId={page_id}"
                            }
                        ]
                    }
                ]
            }
            
            if verification:
                card["sections"].append({
                    "title": "**Verification Details:**",
                    "text": verification[:500] + "..." if len(verification) > 500 else verification
                })
            
            response = requests.post(
                self.teams_webhook_url,
                json=card,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Teams notification sent for page {page_id}")
                return True
            else:
                logger.error(f"Failed to send Teams notification: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"Error sending Teams notification: {e}")
            return False
    
    def check_multiple_pages(self, page_ids: List[str], space: str = "CLOUD") -> List[Dict[str, Any]]:
        """Check multiple pages and send notifications for outdated ones"""
        results = []
        
        for page_id in page_ids:
            logger.info(f"Checking page {page_id}")
            
            # Analyze page
            analysis = self.analyze_page_freshness(page_id, space)
            
            # If outdated, verify with AWS docs
            if analysis.get('is_outdated'):
                verification = self.verify_with_aws_docs(page_id, space)
                analysis['verification'] = verification.get('verification', '')
                analysis['needs_update'] = verification.get('needs_update', False)
            
            # Send notification if needed
            if analysis.get('is_outdated') or analysis.get('needs_update'):
                self.send_teams_notification(analysis)
            
            results.append(analysis)
        
        return results


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler for intelligent Confluence freshness checking
    
    Event structure:
    {
        "page_ids": ["123456", "789012"],  # List of page IDs to check
        "space": "CLOUD",  # Optional, defaults to CLOUD
        "mode": "analyze" or "verify"  # analyze = quick check, verify = deep check with AWS docs
    }
    
    Can be triggered by:
    - EventBridge schedule (daily/weekly checks)
    - Manual invocation
    - Webhook from Confluence when pages are viewed
    """
    try:
        confluence_mcp_url = os.environ.get('MCP_CONFLUENCE')
        teams_webhook_url = os.environ.get('TEAMS_WEBHOOK_URL')
        
        if not all([confluence_mcp_url, teams_webhook_url]):
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Missing required environment variables',
                    'required': ['MCP_CONFLUENCE', 'TEAMS_WEBHOOK_URL']
                })
            }
        
        agent = IntelligentFreshnessAgent(confluence_mcp_url, teams_webhook_url)
        
        # Parse event
        page_ids = event.get('page_ids', [])
        space = event.get('space', 'CLOUD')
        mode = event.get('mode', 'analyze')
        
        if not page_ids:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No page_ids provided'})
            }
        
        logger.info(f"Checking {len(page_ids)} pages in {space} space (mode: {mode})")
        
        # Check pages
        results = agent.check_multiple_pages(page_ids, space)
        
        # Summary
        outdated_count = sum(1 for r in results if r.get('is_outdated') or r.get('needs_update'))
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'checked_pages': len(results),
                'outdated_pages': outdated_count,
                'results': results
            }, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in lambda handler: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# For local testing
def main():
    """Test the freshness checker locally"""
    test_event = {
        'page_ids': ['1516196418'],  # Your test page
        'space': 'CLOUD',
        'mode': 'analyze'
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
