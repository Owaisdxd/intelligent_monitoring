# infrastructure/aws-eks-cluster.tf

provider "aws" {
  region = "us-east-1"
}

# 1. Define the VPC for the Cluster
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "observability-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

# 2. Provision the EKS Cluster
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = "observability-cluster"
  cluster_version = "1.28"

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  cluster_endpoint_public_access = true

  # 3. Define the Worker Nodes (Where your monitoring tools will run)
  eks_managed_node_groups = {
    monitoring_nodes = {
      min_size     = 2
      max_size     = 4
      desired_size = 2

      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
      
      labels = {
        role = "monitoring-workload"
      }
    }
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}