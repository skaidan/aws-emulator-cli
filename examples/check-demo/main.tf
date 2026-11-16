# Infrastructure for orders.py, to try 'awsemu check examples/check-demo'.

resource "aws_dynamodb_table" "orders" {
  name         = "orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_sqs_queue" "orders" {
  name = "orders"
}
