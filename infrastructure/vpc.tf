resource "aws_vpc" "cactuscon" {
  cidr_block = "10.14.0.0/16"

  tags = {
    Name = "cactuscon14-public-vpc"
  }
}

resource "aws_internet_gateway" "cactuscon" {
  vpc_id = aws_vpc.cactuscon.id

  tags = {
    Name = "cactuscon14-public-igw"
  }
}

resource "aws_subnet" "cactuscon" {
  vpc_id            = aws_vpc.cactuscon.id
  cidr_block        = "10.14.0.0/24"
  availability_zone = "us-east-1c"

  tags = {
    Name = "cactuscon14-public-sn"
  }
}

resource "aws_default_route_table" "cactuscon" {
  default_route_table_id = aws_vpc.cactuscon.default_route_table_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.cactuscon.id
  }

  route {
    ipv6_cidr_block = "::/0"
    gateway_id      = aws_internet_gateway.cactuscon.id
  }

  tags = {
    Name = "cactuscon14-public-rt"
  }
}
