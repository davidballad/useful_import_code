# Terraform Standards for Kiro

This folder contains the Terraform infrastructure standards that can be imported into any repository using Kiro.

## Installation

Copy the `terraform-standards.md` file to your repository's Kiro steering directory:

```bash
# In your target repository
mkdir -p .kiro/steering
cp terraform-standards.md .kiro/steering/
```

## What This Does

Once installed, Kiro will automatically:
- Follow your organization's Terraform structure conventions
- Use consistent file naming (underscore prefixes for core files)
- Create separate files per resource type
- Include required variables and locals
- Tag all resources properly
- Follow best practices for IAM, logging, and monitoring

## Customization

You can customize the standards by editing `terraform-standards.md`:

1. **Change default tags** - Update the `tags` variable default values
2. **Add/remove required variables** - Modify the "Required Variables" section
3. **Adjust naming conventions** - Update the "Naming Conventions" section
4. **Add organization-specific rules** - Add new sections as needed

## Inclusion Mode

The file is set to `inclusion: always` which means it applies to all Terraform work automatically.

If you want it to only apply when specific files are open, change the frontmatter to:
```yaml
---
inclusion: fileMatch
fileMatchPattern: '*.tf'
---
```

## Usage

After installation, simply ask Kiro to create or modify Terraform code, and it will automatically follow these standards.

Example prompts:
- "Create a Terraform module for an S3 bucket"
- "Add monitoring to my Lambda function"
- "Create a new environment config for staging"

Kiro will structure everything according to your standards!
