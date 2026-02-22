terraform {
  backend "s3" {
    bucket         = "cactuscon14-terraform"
    key            = "infrastructure.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cactuscon14-terraform"
    encrypt        = true
  }
}
