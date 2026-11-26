# Terraform against AWS Emulator.
#
#   awsemu exec -- terraform init
#   awsemu exec -- terraform apply -auto-approve
#
# The provider block has nothing emulator-specific: the AWS provider reads the
# endpoint (AWS_ENDPOINT_URL), region, credentials and certificate (AWS_CA_BUNDLE)
# from the environment awsemu sets. The same configuration deploys to AWS.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80"
    }
  }
}

provider "aws" {}

resource "aws_s3_bucket" "uploads" {
  bucket = "tf-example-uploads"
}

resource "aws_sqs_queue" "jobs_dlq" {
  name = "tf-example-jobs-dlq"
}

resource "aws_sqs_queue" "jobs" {
  name = "tf-example-jobs"
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_dynamodb_table" "orders" {
  name         = "tf-example-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_ssm_parameter" "queue_url" {
  name  = "/tf-example/queue-url"
  type  = "String"
  value = aws_sqs_queue.jobs.url
}

output "queue_url" {
  value = aws_sqs_queue.jobs.url
}
