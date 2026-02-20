# Confluence Freshness Checker

Automatically detect outdated AWS information in Confluence pages and send MS Teams notifications with update recommendations.

## Overview

This system uses AI agents with MCP (Model Context Protocol) to:
1. Read Confluence pages via Confluence MCP
2. Extract AWS-related claims and information
3. Detect outdated content (deprecated features, old versions, legacy practices)
4. Send detailed MS Teams notifications with recommendations

## Architecture

```
EventBridge Schedule (daily)
    ↓
Lambda Function (intelligent_freshness_agent.py)
    ↓
Strands Agent + Confluence MCP
    ↓
AI Analysis of Page Content
    ↓
MS Teams Notification (if outdated)
```

## Components

### Lambda Functions

1. **`intelligent_freshness_agent.py`** (Recommended)
   - Uses Strands Agent with MCP tools
   - AI-powered semantic analysis
   - Intelligent detection of outdated content
   - Main handler: `lambda_handler()`

2. **`confluence_freshness_checker.py`** (Basic)
   - Simple keyword-based detection
   - Manual AWS topic extraction
   - Fallback option if AI agent not available

3. **`agent.py`** (Supporting)
   - Shared agent utilities and helpers
   - Webex integration functions
   - Bot metrics and DynamoDB operations
   - Confluence update workflow handlers

4. **`s3_memory.py`** (Supporting)
   - S3-based conversation memory storage
   - Chat history persistence
   - Session management utilities

### Terraform Infrastructure

Located in `terraform/confluence_freshness/`:
- `_data.tf` - Data sources
- `_locals.tf` - Local values and naming
- `_variables.tf` - Input variables
- `iam.tf` - IAM roles and policies
- `lambda.tf` - Lambda function and layer
- `eventbridge.tf` - Scheduled triggers
- `logs.tf` - CloudWatch logs
- `monitoring.tf` - CloudWatch alarms
- `outputs.tf` - Output values

## Prerequisites

1. **Confluence MCP Server** - Must be deployed and accessible
   - API Gateway URL for Confluence MCP
   - Confluence credentials configured

2. **MS Teams Webhook** - Incoming webhook URL for notifications

3. **AWS Resources**
   - Lambda execution role with permissions
   - S3 bucket for Terraform state
   - DynamoDB table for state locking
   - S3 bucket for conversation memory (optional, if using s3_memory.py)
   - DynamoDB table for bot metrics (optional, if using agent.py features)

4. **Dependencies Layer**
   - Python packages: requests, boto3, strands, mcp
   - Package as Lambda layer

## Installation

### 1. Prepare Dependencies Layer

```bash
# Create layer directory
mkdir -p layer_package/python

# Install dependencies
pip install -r lambda/requirements.txt -t layer_package/python/

# Create layer zip
cd layer_package
zip -r ../confluence-freshness-layer.zip python/
cd ..
```

### 2. Configure Environment

Edit `terraform/config/dev/variables.tfvars`:

```hcl
# Update these values
confluence_mcp_url = "https://your-confluence-mcp-url.amazonaws.com/prod"
teams_webhook_url  = "https://outlook.office.com/webhook/YOUR_WEBHOOK_URL"
confluence_url     = "https://your-confluence.atlassian.net"

# Add page IDs to monitor
page_ids_to_check = [
  "123456",
  "789012"
]
```

Edit `terraform/config/dev/backend.tfvars`:

```hcl
bucket = "your-terraform-state-bucket"
```

### 3. Deploy Infrastructure

```bash
cd terraform/confluence_freshness

# Initialize Terraform
terraform init -backend-config=../config/dev/backend.tfvars

# Review plan
terraform plan -var-file=../config/dev/variables.tfvars

# Deploy
terraform apply -var-file=../config/dev/variables.tfvars
```

## Usage

### Automatic Checks

The system runs automatically on the configured schedule (default: daily at 9 AM UTC).

### Manual Invocation

Test the function manually:

```bash
aws lambda invoke \
  --function-name confluence-freshness-dev \
  --payload '{
    "page_ids": ["123456"],
    "space": "CLOUD",
    "mode": "analyze"
  }' \
  response.json

cat response.json
```

### Event Payload

```json
{
  "page_ids": ["123456", "789012"],  // List of page IDs to check
  "space": "CLOUD",                   // Confluence space key
  "mode": "analyze"                   // "analyze" or "verify"
}
```

## Configuration

### Environment Variables

Set in Lambda function:
- `MCP_CONFLUENCE` - Confluence MCP API Gateway URL
- `TEAMS_WEBHOOK_URL` - MS Teams incoming webhook URL
- `CONFLUENCE_URL` - Base Confluence URL
- `CONFLUENCE_SPACE` - Default space to check (default: CLOUD)
- `LOG_LEVEL` - Logging level (default: INFO)

### Schedule

Modify in `terraform/confluence_freshness/eventbridge.tf`:

```hcl
# Daily at 9 AM UTC
schedule_expression = "cron(0 9 * * ? *)"

# Every 12 hours
schedule_expression = "rate(12 hours)"

# Weekly on Monday at 9 AM
schedule_expression = "cron(0 9 ? * MON *)"
```

### Pages to Monitor

Add page IDs in `terraform/config/dev/variables.tfvars`:

```hcl
page_ids_to_check = [
  "1516196418",  # AWS Best Practices
  "2345678901",  # Lambda Guidelines
  "3456789012"   # S3 Documentation
]
```

## MS Teams Notification Format

Notifications include:
- **Page Title** and ID
- **Outdated Status** with confidence level
- **AI Analysis** of what's outdated and why
- **Action Buttons**:
  - View Page in Confluence
  - Update Page (direct edit link)

## Monitoring

### CloudWatch Logs

View logs:
```bash
aws logs tail /aws/lambda/confluence-freshness-dev --follow
```

### CloudWatch Alarms

Two alarms are configured:
1. **Error Alarm** - Triggers if >5 errors in 5 minutes
2. **Duration Alarm** - Triggers if execution time >4 minutes

### Metrics

Monitor in CloudWatch:
- Invocations
- Errors
- Duration
- Throttles

## Troubleshooting

### Lambda Timeout

If checks take too long:
1. Increase `lambda_timeout` in variables.tfvars
2. Reduce number of pages checked per invocation
3. Split into multiple scheduled runs

### MCP Connection Issues

Check:
1. Confluence MCP URL is correct and accessible
2. Lambda has network access to MCP endpoint
3. MCP server is running and healthy

### No Notifications Sent

Verify:
1. Teams webhook URL is correct
2. Pages are actually outdated (check logs)
3. Lambda has internet access to send to Teams

### Permission Errors

Ensure Lambda role has:
- CloudWatch Logs permissions
- Secrets Manager access (if using)
- VPC permissions (if in VPC)

## Development

### Local Testing

```python
# In lambda/intelligent_freshness_agent.py
if __name__ == "__main__":
    test_event = {
        'page_ids': ['1516196418'],
        'space': 'CLOUD',
        'mode': 'analyze'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
```

Run locally:
```bash
cd lambda
python intelligent_freshness_agent.py
```

### Adding New Features

1. Modify `intelligent_freshness_agent.py`
2. Update Terraform if needed
3. Test locally
4. Deploy with `terraform apply`

## Cost Estimation

Approximate monthly costs (us-east-1):
- Lambda invocations: ~$0.20 (daily checks)
- CloudWatch Logs: ~$0.50 (7-day retention)
- EventBridge: Free (included)
- **Total: ~$0.70/month**

## Security

- Secrets stored in AWS Secrets Manager
- Teams webhook URL marked as sensitive
- Lambda uses least-privilege IAM role
- All data encrypted at rest
- VPC deployment optional

## Support

For issues or questions:
1. Check CloudWatch logs
2. Review Terraform plan output
3. Verify MCP server connectivity
4. Test with manual invocation

## License

Internal use only - follow your organization's policies.
