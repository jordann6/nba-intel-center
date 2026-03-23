terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}

resource "azurerm_resource_group" "nba_intel" {
  name     = "rg-nba-intel-center"
  location = var.location
}

resource "azurerm_cognitive_account" "openai" {
  name                = "nba-intel-openai"
  location            = azurerm_resource_group.nba_intel.location
  resource_group_name = azurerm_resource_group.nba_intel.name
  kind                = "OpenAI"
  sku_name            = "S0"
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-11-20"
  }

  sku {
    name     = "Standard"
    capacity = 10
  }
}

resource "azurerm_consumption_budget_resource_group" "nba_intel_budget" {
  name              = "nba-intel-budget"
  resource_group_id = azurerm_resource_group.nba_intel.id
  amount            = 20
  time_grain        = "Monthly"

  time_period {
    start_date = "2026-04-01T00:00:00Z"
    end_date   = "2027-04-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    contact_emails = [var.alert_email]
  }
}