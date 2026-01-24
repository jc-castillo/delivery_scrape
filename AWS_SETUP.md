# AWS Setup for Common Crawl Access

This guide explains how to set up AWS credentials for faster access to Common Crawl data.

## Why Use AWS?

Common Crawl data is stored in Amazon S3. While you can access it anonymously (without credentials), using AWS credentials provides:

1. **Faster access**: No rate limiting
2. **Better reliability**: Fewer connection failures
3. **Cost-effective**: Common Crawl data is in a "requester pays" bucket, but the costs are minimal (around $0.09/GB for data transfer within US regions)

## Step 1: Create an AWS Account

If you don't have one:
1. Go to https://aws.amazon.com/
2. Click "Create an AWS Account"
3. Follow the signup process
4. You'll need a credit card, but the costs for this project should be very low

## Step 2: Create IAM Credentials

1. Log in to AWS Console: https://console.aws.amazon.com/
2. Go to **IAM** (Identity and Access Management)
3. Click **Users** → **Add users**
4. Enter a username (e.g., `commoncrawl-scraper`)
5. Click **Next**

### Attach Permissions

6. Select **Attach policies directly**
7. Search for and select: `AmazonS3ReadOnlyAccess`
8. Click **Next** → **Create user**

### Create Access Key

9. Click on the user you just created
10. Go to **Security credentials** tab
11. Click **Create access key**
12. Select **Command Line Interface (CLI)**
13. Confirm and create the key
14. **IMPORTANT**: Download the CSV or copy both:
    - Access Key ID
    - Secret Access Key

You won't be able to see the secret key again!

## Step 3: Configure Your Environment

### Option A: Environment Variables (Recommended)

Add these to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_REGION="us-east-1"
```

Then reload your shell:
```bash
source ~/.bashrc  # or ~/.zshrc
```

### Option B: AWS CLI Configuration

Install AWS CLI and configure:

```bash
# Install AWS CLI
pip install awscli

# Configure
aws configure
```

Enter your credentials when prompted. This creates `~/.aws/credentials`.

### Option C: Edit config.py Directly

Not recommended for security, but you can edit `code/config.py`:

```python
AWS_ACCESS_KEY_ID = "your-access-key-id"
AWS_SECRET_ACCESS_KEY = "your-secret-access-key"
```

## Step 4: Verify Setup

Run this test:

```bash
cd code
python -c "
from cc_index import CommonCrawlIndex
cc = CommonCrawlIndex()
print('Connection successful!')
"
```

## Cost Estimation

Common Crawl data is in an S3 bucket with "requester pays" enabled. Costs:

- **Data transfer (to internet)**: ~$0.09/GB
- **GET requests**: $0.0004 per 1,000 requests

For a typical scraping session:
- Querying the index: ~10-50 MB per crawl → minimal cost
- Downloading HTML: ~1-5 KB per page
- 100,000 pages ≈ 500 MB → ~$0.05

**Total estimated cost for full project: $1-10**

## Troubleshooting

### "Access Denied" Error
- Verify your credentials are correct
- Ensure the IAM user has S3 read permissions
- Check that `AWS_REGION` is set to `us-east-1` (where Common Crawl data is stored)

### "Request limit exceeded"
- You're using anonymous access; set up credentials
- Or wait and retry with exponential backoff

### Slow Downloads
- Data is in `us-east-1`; running from a US-based machine is faster
- Consider using an EC2 instance in `us-east-1` for bulk downloads

## Alternative: Use CDX API (No AWS Needed)

If you prefer not to set up AWS, the code can use the public CDX API:

```bash
# Uses CDX API (slower, may be rate-limited)
python run_pipeline.py --all --crawl CC-MAIN-2024-51

# Force S3 access (requires AWS credentials)
python run_pipeline.py --all --use-s3
```

The CDX API is free but has rate limits. For large-scale scraping, AWS credentials are strongly recommended.

## Security Best Practices

1. **Never commit credentials** to git
2. **Use environment variables** instead of hardcoding
3. **Restrict IAM permissions** to only what's needed (S3 read-only)
4. **Rotate keys periodically**
5. Add `.env` to `.gitignore` if using dotenv files

## EC2 Alternative (For Large-Scale Scraping)

For processing many crawls, consider running on EC2 in `us-east-1`:

1. Launch a small EC2 instance (t3.medium is sufficient)
2. Data transfer within AWS is free
3. Much faster than downloading to your local machine
4. Process data on EC2, then download only the final CSV

This can reduce costs significantly for large-scale operations.
