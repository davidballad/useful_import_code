# Package Contents

Complete Confluence Freshness Checker - Ready to Deploy

## 📦 What's Included

### Lambda Functions (4 files)
```
lambda/
├── intelligent_freshness_agent.py  ⭐ Main AI-powered checker
├── confluence_freshness_checker.py    Basic fallback version
├── agent.py                           Shared utilities & Webex integration
├── s3_memory.py                       S3 conversation storage
└── requirements.txt                   Python dependencies
```

### Terraform Infrastructure (Complete Module)
```
terraform/
├── confluence_freshness/
│   ├── _data.tf          Data sources
│   ├── _locals.tf        Local values & naming
│   ├── _variables.tf     Input variables
│   ├── iam.tf           IAM roles & policies
│   ├── lambda.tf        Lambda function & layer
│   ├── eventbridge.tf   Scheduled triggers
│   ├── logs.tf          CloudWatch logs
│   ├── monitoring.tf    CloudWatch alarms
│   └── outputs.tf       Output values
└── config/dev/
    ├── backend.tfvars    Backend configuration
    └── variables.tfvars  Environment variables
```

### Documentation (4 files)
```
docs/
├── ARCHITECTURE.md      System design & architecture
├── DEPLOYMENT.md        Step-by-step deployment guide
└── FILE_REFERENCE.md    Complete file reference
```

### Root Files
```
├── README.md            Main documentation
├── .gitignore          Git ignore patterns
└── PACKAGE_CONTENTS.md  This file
```

## 🎯 Purpose

Automatically detect outdated AWS information in Confluence pages and send MS Teams notifications with update recommendations.

## ⚡ Quick Start

1. **Copy to your repo**
   ```bash
   cp -r confluence-freshness-export/* your-repo/
   ```

2. **Update configuration**
   ```bash
   # Edit these files:
   terraform/config/dev/backend.tfvars
   terraform/config/dev/variables.tfvars
   ```

3. **Deploy**
   ```bash
   cd terraform/confluence_freshness
   terraform init -backend-config=../config/dev/backend.tfvars
   terraform apply -var-file=../config/dev/variables.tfvars
   ```

## 📚 Documentation Guide

### For First-Time Users
1. Start with **README.md** - Understand what the system does
2. Read **docs/ARCHITECTURE.md** - Understand how it works
3. Follow **docs/DEPLOYMENT.md** - Deploy step-by-step

### For Developers
1. Review **docs/FILE_REFERENCE.md** - Understand each file
2. Check **lambda/intelligent_freshness_agent.py** - Main logic
3. Review **terraform/** files - Infrastructure code

### For Operators
1. Check **docs/DEPLOYMENT.md** - Deployment procedures
2. Review **README.md** - Configuration and monitoring
3. Check **terraform/config/** - Environment settings

## 🔑 Key Features

### AI-Powered Analysis
- Uses Strands Agent with MCP tools
- Semantic understanding of page content
- Intelligent detection of outdated information

### Automated Monitoring
- Scheduled checks via EventBridge
- Configurable frequency (daily by default)
- Batch processing of multiple pages

### MS Teams Integration
- Rich adaptive cards
- Detailed analysis and recommendations
- Direct links to view/edit pages

### Complete Infrastructure
- Lambda function with dependencies
- IAM roles with least privilege
- CloudWatch logs and alarms
- EventBridge scheduling

## 🛠️ What You Need

### Required
- AWS account with appropriate permissions
- Confluence MCP server deployed
- MS Teams incoming webhook
- Terraform installed
- Python 3.11+

### Optional
- S3 bucket for conversation memory (if using s3_memory.py)
- DynamoDB table for bot metrics (if using agent.py features)
- Webex bot token (if using agent.py Webex features)

## 📋 Files by Purpose

### Core Functionality
- `lambda/intelligent_freshness_agent.py` - Main application
- `terraform/confluence_freshness/lambda.tf` - Lambda deployment
- `terraform/config/dev/variables.tfvars` - Configuration

### Supporting Features
- `lambda/agent.py` - Webex bot integration
- `lambda/s3_memory.py` - Conversation storage
- `lambda/confluence_freshness_checker.py` - Basic fallback

### Infrastructure
- `terraform/confluence_freshness/*.tf` - All infrastructure
- `terraform/config/dev/*.tfvars` - Environment config

### Documentation
- `README.md` - Overview and usage
- `docs/ARCHITECTURE.md` - Technical design
- `docs/DEPLOYMENT.md` - Deployment guide
- `docs/FILE_REFERENCE.md` - File details

## 🚀 Deployment Options

### Minimal Deployment
Just the freshness checker:
- `intelligent_freshness_agent.py`
- Terraform infrastructure
- MS Teams webhook

### Full Deployment
All features:
- All Lambda functions
- S3 memory storage
- DynamoDB metrics
- Webex integration

## 💰 Cost Estimate

**Minimal deployment:** ~$0.70/month
- Lambda: $0.20
- CloudWatch Logs: $0.50
- EventBridge: Free

**Full deployment:** ~$2.00/month
- Lambda: $0.50
- CloudWatch Logs: $0.50
- S3: $0.50
- DynamoDB: $0.50

## 🔒 Security

- Secrets in AWS Secrets Manager
- Least privilege IAM roles
- Encrypted data at rest
- HTTPS only communication
- No hardcoded credentials

## 📊 Monitoring

### CloudWatch Logs
- `/aws/lambda/confluence-freshness-{env}`
- 7-day retention

### CloudWatch Alarms
- Error alarm (>5 errors in 5 min)
- Duration alarm (>4 min execution)

### Metrics
- Invocations
- Errors
- Duration
- Outdated pages detected

## 🔧 Customization

### Change Schedule
Edit `terraform/config/dev/variables.tfvars`:
```hcl
check_schedule = "cron(0 9 * * ? *)"  # Daily at 9 AM UTC
```

### Add Pages to Monitor
Edit `terraform/config/dev/variables.tfvars`:
```hcl
page_ids_to_check = [
  "123456",
  "789012"
]
```

### Adjust Lambda Resources
Edit `terraform/config/dev/variables.tfvars`:
```hcl
lambda_timeout = 300  # 5 minutes
lambda_memory  = 512  # 512 MB
```

## 🆘 Support

### Troubleshooting
1. Check CloudWatch logs
2. Review Terraform plan output
3. Verify MCP connectivity
4. Test with manual invocation

### Common Issues
- **No notifications:** Check Teams webhook URL
- **Timeout errors:** Increase lambda_timeout
- **MCP errors:** Verify MCP URL and connectivity
- **Permission errors:** Check IAM role permissions

## 📝 License

Internal use only - follow your organization's policies.

## 🎉 Ready to Deploy!

Everything you need is in this package. Follow the deployment guide and you'll be up and running in minutes!

**Next Steps:**
1. Read README.md
2. Update configuration files
3. Follow docs/DEPLOYMENT.md
4. Deploy and test!
