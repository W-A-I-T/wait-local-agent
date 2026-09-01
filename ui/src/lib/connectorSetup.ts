export type ConnectorSetupTier = "env" | "instance";

export type ConnectorSetup = {
  label: string;
  tier: ConnectorSetupTier;
  envVars: readonly string[];
  docsNote: string;
};

export const connectorSetup = {
  halopsa: {
    label: "HaloPSA",
    tier: "instance",
    envVars: [
      "WAIT_HALOPSA_BASE_URL",
      "WAIT_HALOPSA_CLIENT_ID",
      "WAIT_HALOPSA_CLIENT_SECRET",
      "WAIT_HALOPSA_TENANT",
      "WAIT_HALOPSA_TOKEN_URL",
      "WAIT_HALOPSA_TICKET_WRITE_ENDPOINT",
      "WAIT_HALOPSA_ACTION_WRITE_ENDPOINT",
      "WAIT_HALOPSA_CLIENT_MAP_JSON"
    ],
    docsNote: "Use appliance-wide HaloPSA settings for one shared connection, or use a Connector Instance when each WAIT client needs its own credentials."
  },
  connectwise: {
    label: "ConnectWise PSA",
    tier: "instance",
    envVars: [
      "WAIT_CONNECTWISE_BASE_URL",
      "WAIT_CONNECTWISE_COMPANY",
      "WAIT_CONNECTWISE_PUBLIC_KEY",
      "WAIT_CONNECTWISE_PRIVATE_KEY",
      "WAIT_CONNECTWISE_CLIENT_ID",
      "WAIT_CONNECTWISE_API_VERSION",
      "WAIT_CONNECTWISE_PAGE_SIZE"
    ],
    docsNote: "Use appliance-wide ConnectWise settings for one shared connection, or use a Connector Instance when each WAIT client needs its own credentials."
  },
  hudu: {
    label: "Hudu",
    tier: "env",
    envVars: ["WAIT_HUDU_BASE_URL", "WAIT_HUDU_API_KEY", "WAIT_HUDU_PAGE_SIZE"],
    docsNote: "Hudu is configured at appliance scope for read-only documentation lookup."
  },
  itglue: {
    label: "IT Glue",
    tier: "env",
    envVars: ["WAIT_ITGLUE_BASE_URL", "WAIT_ITGLUE_API_KEY", "WAIT_ITGLUE_PAGE_SIZE"],
    docsNote: "IT Glue is configured at appliance scope for read-only documentation lookup."
  },
  confluence: {
    label: "Confluence Cloud",
    tier: "env",
    envVars: [
      "WAIT_CONFLUENCE_BASE_URL",
      "WAIT_CONFLUENCE_EMAIL",
      "WAIT_CONFLUENCE_API_TOKEN",
      "WAIT_CONFLUENCE_PAGE_SIZE"
    ],
    docsNote: "Confluence Cloud is configured at appliance scope for read-only page lookup."
  },
  notion: {
    label: "Notion",
    tier: "env",
    envVars: [
      "WAIT_NOTION_BASE_URL",
      "WAIT_NOTION_API_TOKEN",
      "WAIT_NOTION_VERSION",
      "WAIT_NOTION_PAGE_SIZE",
      "WAIT_NOTION_CLIENT_PAGE_MAP_JSON",
      "WAIT_NOTION_CLIENT_DATA_SOURCE_MAP_JSON"
    ],
    docsNote: "Notion is configured at appliance scope with tenant mappings for bounded page reads and approval-gated comments."
  },
  sharepoint: {
    label: "SharePoint",
    tier: "env",
    envVars: ["WAIT_SHAREPOINT_BASE_URL", "WAIT_SHAREPOINT_ACCESS_TOKEN", "WAIT_SHAREPOINT_PAGE_SIZE"],
    docsNote: "SharePoint is configured at appliance scope for bounded Microsoft Graph site and document lookup."
  },
  syncro: {
    label: "Syncro",
    tier: "env",
    envVars: ["WAIT_SYNCRO_BASE_URL", "WAIT_SYNCRO_API_TOKEN"],
    docsNote: "Syncro is configured at appliance scope for read-only ticket and customer lookup."
  },
  servicenow: {
    label: "ServiceNow",
    tier: "env",
    envVars: [
      "WAIT_SERVICENOW_BASE_URL",
      "WAIT_SERVICENOW_USERNAME",
      "WAIT_SERVICENOW_PASSWORD",
      "WAIT_SERVICENOW_API_VERSION",
      "WAIT_SERVICENOW_PAGE_SIZE"
    ],
    docsNote: "ServiceNow is configured at appliance scope for read-only Table API lookup and approval-gated updates."
  },
  autotask: {
    label: "Autotask PSA",
    tier: "env",
    envVars: [
      "WAIT_AUTOTASK_BASE_URL",
      "WAIT_AUTOTASK_USERNAME",
      "WAIT_AUTOTASK_SECRET",
      "WAIT_AUTOTASK_INTEGRATION_CODE",
      "WAIT_AUTOTASK_PAGE_SIZE"
    ],
    docsNote: "Autotask is configured at appliance scope for read-only PSA lookup and approval-gated ticket actions."
  },
  m365: {
    label: "Microsoft 365 / Entra",
    tier: "env",
    envVars: ["WAIT_M365_GRAPH_BASE_URL", "WAIT_M365_ACCESS_TOKEN", "WAIT_M365_PAGE_SIZE"],
    docsNote: "Microsoft Graph is configured at appliance scope; token acquisition remains external to this appliance."
  },
  timezest: {
    label: "TimeZest",
    tier: "env",
    envVars: ["WAIT_TIMEZEST_BASE_URL", "WAIT_TIMEZEST_API_KEY", "WAIT_TIMEZEST_CLIENT_MAP_JSON"],
    docsNote: "TimeZest is configured at appliance scope with an explicit WAIT-client mapping."
  },
  scalepad: {
    label: "ScalePad",
    tier: "env",
    envVars: [
      "WAIT_SCALEPAD_BASE_URL",
      "WAIT_SCALEPAD_API_KEY",
      "WAIT_SCALEPAD_CLIENT_MAP_JSON",
      "WAIT_SCALEPAD_RISK_TENANT_MAP_JSON",
      "WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON",
      "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON"
    ],
    docsNote: "ScalePad is configured at appliance scope with explicit client and product mappings for bounded read surfaces."
  },
  rmm: {
    label: "RMM",
    tier: "env",
    envVars: [
      "WAIT_NINJAONE_BASE_URL",
      "WAIT_NINJAONE_ACCESS_TOKEN",
      "WAIT_NINJAONE_ORGANIZATION_MAP_JSON",
      "WAIT_NINJAONE_PAGE_SIZE",
      "WAIT_DATTORMM_BASE_URL",
      "WAIT_DATTORMM_ACCESS_TOKEN",
      "WAIT_DATTORMM_SITE_MAP_JSON",
      "WAIT_DATTORMM_PAGE_SIZE",
      "WAIT_NSIGHT_BASE_URL",
      "WAIT_NSIGHT_API_KEY",
      "WAIT_NSIGHT_CLIENT_MAP_JSON",
      "WAIT_NCENTRAL_BASE_URL",
      "WAIT_NCENTRAL_ACCESS_TOKEN",
      "WAIT_NCENTRAL_ORG_UNIT_MAP_JSON",
      "WAIT_NCENTRAL_PAGE_SIZE",
      "WAIT_KASEYA_RMM_BASE_URL",
      "WAIT_KASEYA_RMM_TOKEN_ID",
      "WAIT_KASEYA_RMM_TOKEN_SECRET",
      "WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON",
      "WAIT_KASEYA_RMM_PAGE_SIZE",
      "WAIT_SCREENCONNECT_BASE_URL",
      "WAIT_SCREENCONNECT_EXTENSION_ID",
      "WAIT_SCREENCONNECT_AUTH_SECRET",
      "WAIT_SCREENCONNECT_ORIGIN",
      "WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON",
      "WAIT_SCREENCONNECT_SCRIPT_CATALOG_JSON"
    ],
    docsNote: "The RMM card represents NinjaOne, Datto RMM, N-able N-sight, N-able N-central, Kaseya VSA X, and ScreenConnect. Configure one vendor family at appliance scope with its explicit WAIT-client mapping."
  }
} as const satisfies Record<string, ConnectorSetup>;

export const connectorSetupEnvVarNames = Array.from(
  new Set(Object.values(connectorSetup).flatMap((setup) => setup.envVars))
);
