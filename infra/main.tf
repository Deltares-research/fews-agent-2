# main.tf — FEWS Agent Azure Infrastructure
#
# Single-file Terraform configuration for deploying the Streamlit app
# to Azure Container Apps with Azure AI as the LLM backend.
#
# Usage:
#   cd infra
#   cp terraform.tfvars.example terraform.tfvars  # fill in values
#   terraform init
#   terraform apply

terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "resource_group_name" {
  description = "Name of the existing resource group"
  type        = string
  default     = "FEWS_LLM"
}

variable "azure_ai_api_base" {
  description = "Azure AI endpoint URL"
  type        = string
}

variable "azure_ai_api_key" {
  description = "Azure AI API key"
  type        = string
  sensitive   = true
}

variable "fews_agent_model" {
  description = "Model identifier for the LLM"
  type        = string
  default     = "azure_ai/Llama-3.3-70B-Instruct"
}

# -----------------------------------------------------------------------------
# Random suffix for globally unique names
# -----------------------------------------------------------------------------

resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# Resource Group (existing - not managed by Terraform)
# -----------------------------------------------------------------------------

data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

# -----------------------------------------------------------------------------
# Container Registry
# -----------------------------------------------------------------------------

resource "azurerm_container_registry" "main" {
  name                = "fewsagentacr${random_id.suffix.hex}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = data.azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

# -----------------------------------------------------------------------------
# Container Apps Environment
# -----------------------------------------------------------------------------

resource "azurerm_container_app_environment" "main" {
  name                = "fews-agent-env"
  location            = data.azurerm_resource_group.main.location
  resource_group_name = data.azurerm_resource_group.main.name
}

# -----------------------------------------------------------------------------
# Container App
# -----------------------------------------------------------------------------

resource "azurerm_container_app" "main" {
  name                         = "fews-agent"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = data.azurerm_resource_group.main.name
  revision_mode                = "Single"

  secret {
    name  = "azure-ai-key"
    value = var.azure_ai_api_key
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.main.admin_password
  }

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  template {
    container {
      name   = "fews-agent"
      image  = "${azurerm_container_registry.main.login_server}/fews-agent:latest"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "FEWS_AGENT_PROVIDER"
        value = "litellm"
      }

      env {
        name  = "AZURE_AI_API_BASE"
        value = var.azure_ai_api_base
      }

      env {
        name        = "AZURE_AI_API_KEY"
        secret_name = "azure-ai-key"
      }

      env {
        name  = "FEWS_AGENT_MODEL"
        value = var.fews_agent_model
      }
    }

    min_replicas = 0
    max_replicas = 2
  }

  ingress {
    external_enabled = true
    target_port      = 8501

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "app_url" {
  description = "URL of the deployed Streamlit app"
  value       = "https://${azurerm_container_app.main.ingress[0].fqdn}"
}

output "acr_login_server" {
  description = "ACR login server for Docker push"
  value       = azurerm_container_registry.main.login_server
}

output "acr_name" {
  description = "ACR name (for GitHub Actions)"
  value       = azurerm_container_registry.main.name
}

output "resource_group" {
  description = "Resource group name"
  value       = data.azurerm_resource_group.main.name
}
