resource "aws_iam_role" "cc14-web" {
  name = "cc14-web-role"
  path = "/"

  assume_role_policy = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": "sts:AssumeRole",
            "Principal": {
               "Service": "ec2.amazonaws.com"
            },
            "Effect": "Allow",
            "Sid": ""
        }
    ]
}
EOF

  tags = {
    Name = "cc14-web"
  }
}

resource "aws_iam_policy" "web_data" {
  name        = "cc14-web-data"
  description = "IAM policy for API Service to access DynamoDB and CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = [
          "dynamodb:*"
        ],
        Effect = "Allow",
        Resource = [
          "arn:aws:dynamodb:us-east-1:904233104322:table/cactuscon14_*"
        ],
      },
      {
        "Sid" : "CloudWatchReadAccess",
        "Effect" : "Allow",
        "Action" : [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ],
        "Resource" : "*"
      },
      {
        "Sid" : "EC2InstanceInformation",
        "Effect" : "Allow",
        "Action" : [
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeTags"
        ],
        "Resource" : "*"
      }
    ],
  })
}

resource "aws_iam_role_policy_attachment" "web_data" {
  role       = aws_iam_role.cc14-web.name
  policy_arn = aws_iam_policy.web_data.arn
}

resource "aws_iam_instance_profile" "cc14-web" {
  name = "cc14-web-profile"
  role = aws_iam_role.cc14-web.name
}
