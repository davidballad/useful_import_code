"""
Confluence Page Freshness Checker
Compares Confluence content with current AWS documentation to detect outdated information
"""
import json
import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ConfluenceFreshnessChecker:
    """Check if Confluence pages contain outdated AWS information"""
    
    def __init__(self, confluence_mcp_url: str, aws_mcp_url: str, teams_webhook_url: str):
        self.confluence_mcp_url = confluence_mcp_url
        self.aws_mcp_url = aws_mcp_url
        self.teams_webhook_url = teams_webhook_url
    
    def check_page_freshness(self, page_id: str, space: str = "CLOUD") -> Dict[str, Any]:
        """
        Check if a Confluence page contains outdated AWS information
        
        Returns:
            {
                'is_outdated': bool,
                'outdated_items': List[Dict],
                'page_info': Dict,
                'recommendations': List[str]
            }
        """
        try:
            # Get Confluence page content
            page_content = self._get_confluence_page(page_id, space)
            if not page_content:
                return {'error': 'Could not retrieve page'}
            
            # Extract AWS-related topics from the page
            aws_topics = self._extract_aws_topics(page_content)
            
            # Check each topic against current AWS documentation
            outdated_items = []
            for topic in aws_topics:
                current_info = self._get_current_aws_info(topic)
                if current_info:
                    comparison = self._compare_information(
                        page_content, 
                        current_info, 
                        topic
                    )
                    if comparison['is_outdated']:
                        outdated_items.append(comparison)
            
            return {
                'is_outdated': len(outdated_items) > 0,
                'outdated_items': outdated_items,
                'page_info': {
                    'id': page_id,
                    'title': page_content.get('title'),
                    'space': space,
                    'last_modified': page_content.get('version')
                },
                'recommendations': self._generate_recommendations(outdated_items)
            }
            
        except Exception as e:
            logger.error(f"Error checking page freshness: {e}")
            return {'error': str(e)}
    
    def _get_confluence_page(self, page_id: str, space: str) -> Optional[Dict]:
        """Retrieve Confluence page using MCP"""
        try:
            request_payload = {
                'method': 'tools/call',
                'params': {
                    'name': 'confluence_get_page',
                    'arguments': {
                        'page_id': page_id,
                        'space': space,
                        'expand': 'body.storage,version,history'
                    }
                }
            }
            
            response = requests.post(
                self.confluence_mcp_url,
                json=request_payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content_text = result.get('result', {}).get('content', [{}])[0].get('text', '')
                
                # Parse the response to extract structured data
                return {
                    'title': self._extract_field(content_text, 'title'),
                    'content': content_text,
                    'version': self._extract_field(content_text, 'Version'),
                    'page_id': page_id
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting Confluence page: {e}")
            return None
    
    def _extract_aws_topics(self, page_content: Dict) -> List[str]:
        """Extract AWS service names and topics from page content"""
        content = page_content.get('content', '')
        
        # Common AWS services to check
        aws_services = [
            'EC2', 'S3', 'Lambda', 'RDS', 'DynamoDB', 'CloudFormation',
            'IAM', 'VPC', 'ECS', 'EKS', 'CloudWatch', 'SNS', 'SQS',
            'API Gateway', 'Bedrock', 'SageMaker', 'Step Functions'
        ]
        
        found_topics = []
        content_lower = content.lower()
        
        for service in aws_services:
            if service.lower() in content_lower:
                found_topics.append(service)
        
        return found_topics
    
    def _get_current_aws_info(self, topic: str) -> Optional[str]:
        """Get current AWS information using AWS MCP"""
        try:
            # Use AWS MCP to get current documentation
            # This would call the AWS documentation MCP or AWS CLI MCP
            request_payload = {
                'method': 'tools/call',
                'params': {
                    'name': 'suggest_aws_commands',  # or appropriate AWS MCP tool
                    'arguments': {
                        'query': f"Get latest information about AWS {topic} best practices and features"
                    }
                }
            }
            
            response = requests.post(
                self.aws_mcp_url,
                json=request_payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('result', {}).get('content', [{}])[0].get('text', '')
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting AWS info: {e}")
            return None
    
    def _compare_information(self, page_content: str, current_info: str, topic: str) -> Dict:
        """Compare page content with current AWS information"""
        # This is a simplified comparison - in production, you'd use an LLM
        # to do semantic comparison
        
        # Check for version numbers, deprecated features, etc.
        outdated_indicators = [
            'deprecated',
            'no longer supported',
            'legacy',
            'old version',
            'previous generation'
        ]
        
        is_outdated = any(indicator in current_info.lower() for indicator in outdated_indicators)
        
        return {
            'topic': topic,
            'is_outdated': is_outdated,
            'current_info': current_info[:500],  # Truncate for brevity
            'reason': 'AWS documentation indicates changes or deprecations'
        }
    
    def _generate_recommendations(self, outdated_items: List[Dict]) -> List[str]:
        """Generate update recommendations"""
        recommendations = []
        
        for item in outdated_items:
            recommendations.append(
                f"Update {item['topic']} section: {item['reason']}"
            )
        
        return recommendations
    
    def _extract_field(self, text: str, field_name: str) -> str:
        """Extract a field value from formatted text"""
        try:
            if f"{field_name}:" in text:
                for line in text.split('\n'):
                    if f"{field_name}:" in line:
                        return line.split(f"{field_name}:")[1].split('|')[0].strip()
            return "Unknown"
        except:
            return "Unknown"
    
    def send_teams_notification(self, freshness_result: Dict[str, Any]) -> bool:
        """Send MS Teams notification about outdated page"""
        try:
            if not freshness_result.get('is_outdated'):
                return False
            
            page_info = freshness_result['page_info']
            outdated_items = freshness_result['outdated_items']
            recommendations = freshness_result['recommendations']
            
            # Create adaptive card for Teams
            card = {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": f"Confluence Page Update Needed: {page_info['title']}",
                "themeColor": "FF6B35",
                "title": "🔄 Confluence Page Needs Update",
                "sections": [
                    {
                        "activityTitle": f"**{page_info['title']}**",
                        "activitySubtitle": f"Space: {page_info['space']} | Page ID: {page_info['id']}",
                        "facts": [
                            {
                                "name": "Last Modified",
                                "value": page_info.get('last_modified', 'Unknown')
                            },
                            {
                                "name": "Outdated Items",
                                "value": str(len(outdated_items))
                            }
                        ]
                    },
                    {
                        "title": "**Outdated Information Detected:**",
                        "text": "\n\n".join([
                            f"• **{item['topic']}**: {item['reason']}"
                            for item in outdated_items[:5]  # Limit to 5
                        ])
                    },
                    {
                        "title": "**Recommended Updates:**",
                        "text": "\n\n".join([f"• {rec}" for rec in recommendations[:5]])
                    }
                ],
                "potentialAction": [
                    {
                        "@type": "OpenUri",
                        "name": "View Page in Confluence",
                        "targets": [
                            {
                                "os": "default",
                                "uri": f"{os.environ.get('CONFLUENCE_URL', '')}/pages/viewpage.action?pageId={page_info['id']}"
                            }
                        ]
                    }
                ]
            }
            
            response = requests.post(
                self.teams_webhook_url,
                json=card,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error sending Teams notification: {e}")
            return False


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler for scheduled Confluence freshness checks
    
    Event can contain:
    - page_ids: List of page IDs to check
    - space: Confluence space (default: CLOUD)
    - check_all: Boolean to check all pages in space
    """
    try:
        confluence_mcp_url = os.environ.get('MCP_CONFLUENCE')
        aws_mcp_url = os.environ.get('MCP_AWS')  # You'll need to add this
        teams_webhook_url = os.environ.get('TEAMS_WEBHOOK_URL')
        
        if not all([confluence_mcp_url, aws_mcp_url, teams_webhook_url]):
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Missing required environment variables'})
            }
        
        checker = ConfluenceFreshnessChecker(
            confluence_mcp_url,
            aws_mcp_url,
            teams_webhook_url
        )
        
        # Get pages to check from event
        page_ids = event.get('page_ids', [])
        space = event.get('space', 'CLOUD')
        
        results = []
        for page_id in page_ids:
            logger.info(f"Checking page: {page_id}")
            result = checker.check_page_freshness(page_id, space)
            
            if result.get('is_outdated'):
                # Send Teams notification
                checker.send_teams_notification(result)
            
            results.append(result)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'checked_pages': len(results),
                'outdated_pages': sum(1 for r in results if r.get('is_outdated')),
                'results': results
            })
        }
        
    except Exception as e:
        logger.error(f"Error in lambda handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
