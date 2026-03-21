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

  scale {
    type     = "Standard"
    capacity = 10
  }
}