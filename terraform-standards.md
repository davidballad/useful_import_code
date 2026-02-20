---
inclusion: always
---

# Terraform Infrastructure Standards

This document defines the standard structure and conventions for all Terraform infrastructure in this organization.

## Directory Structure

All Terraform code must follow this structure:

```
terraform/
├── <module_name>/              # One directory per logical module
│   ├── _data.tf               # All data sources (except archive_file)
│   ├── _locals.tf             # Local values and computed variables
│   ├── _variables.tf          # Input variable definitions
│   ├── _versions.tf           # Terraform and provider version constraints
│   ├── _providers.tf          # Provider configurations (if module-specific)
│   ├── <resource_type>.tf     # One file per resource type (e.g., lambda.tf, iam.tf)
│   └── outputs.tf             # Output definitions
├── config/
│   ├── dev/
│   │   ├── backend.tfvars     # Backend configuration for dev
│   │   └── variables.tfvars   # Variable values for dev
│   ├── test/
│   │   ├── backend.tfvars     # Backend configuration for test
│   │   └── variables.tfvars   # Variable values for test
│   ├── prod/
│   │   ├── backend.tfvars     # Backend configuration for prod
│   │   └── variables.tfvars   # Variable values for prod
│   └── sdbx/                  # Optional sandbox environment
│       ├── backend.tfvars
│       └── variables.tfvars
└── main.tf                    # Root module that calls child modules
```

## File Naming Conventions

### Core Files (Prefix with underscore)
- `_data.tf` - All data sources except `archive_file` (which goes with its resource)
- `_locals.tf` - Local values, computed names, merged tags
- `_variables.tf` - All input variable declarations
- `_versions.tf` - Terraform and provider version constraints
- `_providers.tf` - Provider configurations (if needed at module level)

### Resource Files (Named by AWS service/resource type)
- `lambda.tf` - Lambda functions and related resources
- `iam.tf` - IAM roles, policies, and attachments
- `api-gateway.tf` - API Gateway resources
- `eventbridge.tf` - EventBridge rules and targets
- `dynamodb.tf` - DynamoDB tables
- `s3.tf` - S3 buckets and policies
- `logs.tf` - CloudWatch log groups
- `monitoring.tf` - CloudWatch alarms and metrics
- `secrets.tf` - Secrets Manager resources
- `vpc.tf` - VPC, subnets, security groups
- `outputs.tf` - Output values (no underscore prefix)

## Required Variables

Every module must include these standard variables in `_variables.tf`:

```hcl
variable "environment" {
  description = "Environment name (dev, test, prod, sdbx)"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Application name"
  type        = string
}

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Pipeline = "TBD"
    Repo     = "TBD"
    P2P      = "TBD"
  }
}
```

## Required Locals

Every module must include these standard locals in `_locals.tf`:

```hcl
locals {
  # Naming conventions
  app_name_dashes      = replace(var.app_name, "_", "-")
  app_name_underscores = replace(var.app_name, "-", "_")
  
  # Common resource naming
  function_name = "${local.app_name_dashes}-${var.environment}"
  
  # Merged tags
  common_tags = merge(
    var.tags,
    {
      Environment = var.environment
      Application = var.app_name
      ManagedBy   = "Terraform"
    }
  )
}
```

## Backend Configuration

Backend configuration must use `app_name_dashes` as the key:

```hcl
# config/dev/backend.tfvars
bucket         = "your-terraform-state-bucket"
key            = "app-name-dashes/dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "terraform-state-lock"
encrypt        = true
```

## Resource Tagging

All resources must be tagged with `local.common_tags`:

```hcl
resource "aws_lambda_function" "example" {
  # ... other configuration ...
  
  tags = merge(
    local.common_tags,
    {
      Name = local.function_name
    }
  )
}
```

## Data Sources

### Placement Rules
- **Standard data sources** → `_data.tf`
- **`archive_file` data sources** → Same file as the resource using it (e.g., in `lambda.tf`)

### Required Data Sources

Include these in `_data.tf` for most modules:

```hcl
data "aws_caller_identity" "current" {}

data "aws_region" "current" {}
```

## IAM Policies

Use `aws_iam_policy_document` data sources for all policies:

```hcl
# In _data.tf
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"
    
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    
    actions = ["sts:AssumeRole"]
  }
}

# In iam.tf
resource "aws_iam_role" "lambda" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  
  tags = local.common_tags
}
```

## Environment Configuration

Each environment must have both files:

### `backend.tfvars`
```hcl
bucket         = "terraform-state-bucket"
key            = "app-name/dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "terraform-state-lock"
encrypt        = true
```

### `variables.tfvars`
```hcl
environment = "dev"
region      = "us-east-1"
app_name    = "my-application"

# Application-specific variables
lambda_timeout = 300
lambda_memory  = 512
```

## Module Organization

### Single Responsibility
Each module directory should represent one logical component:
- `confluence_auto/` - Confluence automation bot
- `confluence_freshness/` - Freshness checker
- `api_gateway/` - Shared API Gateway (if reused)

### Resource Grouping
Group related resources in the same file:
- Lambda function + layer + permissions → `lambda.tf`
- IAM role + policies + attachments → `iam.tf`
- EventBridge rule + targets → `eventbridge.tf`

## Naming Conventions

### Resources
- Use descriptive names: `aws_lambda_function.freshness_checker` not `aws_lambda_function.lambda`
- Use snake_case for resource names
- Include purpose in name: `aws_iam_role.freshness_checker_lambda`

### Variables
- Use snake_case: `lambda_timeout`, `confluence_mcp_url`
- Be descriptive: `teams_webhook_url` not `webhook`
- Mark sensitive variables: `sensitive = true`

### Outputs
- Use snake_case: `lambda_function_arn`
- Include resource type: `lambda_function_name` not just `function_name`

## Lambda-Specific Standards

### Archive Files
Place `archive_file` data source in `lambda.tf`:

```hcl
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../../lambda"
  output_path = "${path.module}/../app-name.zip"
  
  excludes = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests",
    "venv"
  ]
}
```

### Lambda Layers
Define layers in the same module:

```hcl
resource "aws_lambda_layer_version" "dependencies" {
  filename            = "${path.module}/../app-name-layer.zip"
  layer_name          = "${local.function_name}-dependencies"
  compatible_runtimes = ["python3.11"]
  
  description = "Dependencies for ${var.app_name}"
}
```

## CloudWatch Logs

Always create log groups explicitly:

```hcl
# logs.tf
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7
  
  tags = merge(
    local.common_tags,
    {
      Name = "${local.function_name}-logs"
    }
  )
}
```

## Monitoring Standards

Include basic alarms for Lambda functions:

```hcl
# monitoring.tf
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.function_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  
  dimensions = {
    FunctionName = aws_lambda_function.main.function_name
  }
  
  tags = local.common_tags
}
```

## Deployment Commands

### Initialize
```bash
cd terraform/<module_name>
terraform init -backend-config=../config/dev/backend.tfvars
```

### Plan
```bash
terraform plan -var-file=../config/dev/variables.tfvars
```

### Apply
```bash
terraform apply -var-file=../config/dev/variables.tfvars
```

### Destroy
```bash
terraform destroy -var-file=../config/dev/variables.tfvars
```

## Best Practices

1. **Never hardcode values** - Use variables for all environment-specific values
2. **Use data sources** for dynamic lookups (AMIs, availability zones, etc.)
3. **Enable encryption** for all data at rest (S3, DynamoDB, Secrets Manager)
4. **Use least privilege** for IAM policies
5. **Version your providers** in `_versions.tf`
6. **Document variables** with clear descriptions
7. **Use outputs** to expose important resource attributes
8. **Tag everything** with `local.common_tags`
9. **Keep modules focused** - one logical component per module
10. **Use consistent naming** - follow the conventions above

## Example Module Structure

```
terraform/
├── confluence_freshness/
│   ├── _data.tf              # Data sources
│   ├── _locals.tf            # Local values
│   ├── _variables.tf         # Input variables
│   ├── iam.tf                # IAM resources
│   ├── lambda.tf             # Lambda function
│   ├── eventbridge.tf        # EventBridge schedule
│   ├── logs.tf               # CloudWatch logs
│   ├── monitoring.tf         # CloudWatch alarms
│   └── outputs.tf            # Outputs
└── config/
    └── dev/
        ├── backend.tfvars    # Backend config
        └── variables.tfvars  # Variable values
```

## Checklist for New Modules

- [ ] Created module directory under `terraform/`
- [ ] Created `_data.tf` with common data sources
- [ ] Created `_locals.tf` with naming and tags
- [ ] Created `_variables.tf` with required variables
- [ ] Created resource files (one per service type)
- [ ] Created `outputs.tf` with useful outputs
- [ ] Created `logs.tf` for CloudWatch logs
- [ ] Created `monitoring.tf` with basic alarms
- [ ] Created environment configs in `config/dev/`, `config/test/`, `config/prod/`
- [ ] All resources tagged with `local.common_tags`
- [ ] Backend key uses `app_name_dashes`
- [ ] Tested with `terraform plan`
