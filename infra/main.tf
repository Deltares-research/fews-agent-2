# main.tf — FEWS Agent Azure Infrastructure
#
# Single-file Terraform configuration for deploying the Streamlit app
# to Azure App Service (Linux + custom Docker container) with Azure AI
# as the LLM backend.
#
# Usage:
#   cd infra
#   cp terraform.tfvars.example terraform.tfvars  # fill in correct values
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

variable "phase" {
  description = "Session-store phase: dev = local disk only, prod = mirror sessions to Azure Blob (survives container restarts)"
  type        = string
  default     = "prod"
}

variable "azure_storage_connection_string" {
  description = "Storage account connection string for the prod session store (Storage account -> Access keys). Keep secret."
  type        = string
  sensitive   = true
}

variable "azure_storage_container" {
  description = "Blob container holding project sessions (created on first use if absent)"
  type        = string
  default     = "fews-projects"
}

variable "azure_storage_prefix" {
  description = "Optional subpath inside the container for session blobs (e.g. \"projects\"). PERMANENT once chosen - changing it hides all sessions stored under the old prefix."
  type        = string
  default     = ""
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
# App Service Plan (Linux)
# -----------------------------------------------------------------------------

resource "azurerm_service_plan" "main" {
  name                = "fews-agent-plan"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = data.azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "B1"
}

# -----------------------------------------------------------------------------
# App Service (Streamlit container)
# -----------------------------------------------------------------------------

resource "azurerm_linux_web_app" "main" {
  name                = "fews-agent-${random_id.suffix.hex}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = data.azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id

  site_config {
    always_on = true

    application_stack {
      docker_registry_url      = "https://${azurerm_container_registry.main.login_server}"
      docker_image_name        = "fews-agent:latest"
      docker_registry_username = azurerm_container_registry.main.admin_username
      docker_registry_password = azurerm_container_registry.main.admin_password
    }
  }

  app_settings = {
    # App Service routes traffic to this port inside the container.
    WEBSITES_PORT = "8501"

    FEWS_AGENT_PROVIDER = "litellm"
    AZURE_AI_API_BASE   = var.azure_ai_api_base
    AZURE_AI_API_KEY    = var.azure_ai_api_key
    FEWS_AGENT_MODEL    = var.fews_agent_model

    # PHASE-switched session store (app/blob_store.py): prod mirrors project
    # sessions to Azure Blob so they survive container restarts/redeploys
    # (App Service container disk is ephemeral).
    PHASE                           = var.phase
    AZURE_STORAGE_CONNECTION_STRING = var.azure_storage_connection_string
    AZURE_STORAGE_CONTAINER         = var.azure_storage_container
    AZURE_STORAGE_PREFIX            = var.azure_storage_prefix

    # Pull the latest image from ACR on restart.
    DOCKER_ENABLE_CI = "true"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "app_url" {
  description = "URL of the deployed Streamlit app"
  value       = "https://${azurerm_linux_web_app.main.default_hostname}"
}

output "web_app_name" {
  description = "App Service name (for GitHub Actions WEB_APP_NAME secret)"
  value       = azurerm_linux_web_app.main.name
}

output "acr_login_server" {
  description = "ACR login server for Docker push"
  value       = azurerm_container_registry.main.login_server
}

output "acr_name" {
  description = "ACR name"
  value       = azurerm_container_registry.main.name
}

output "acr_username" {
  description = "ACR admin username (for GitHub Actions ACR_USERNAME secret)"
  value       = azurerm_container_registry.main.admin_username
}

output "resource_group" {
  description = "Resource group name"
  value       = data.azurerm_resource_group.main.name
}
