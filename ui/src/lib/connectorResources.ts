export type ConnectorResourceParam = {
  name: string;
  label: string;
  location: "path" | "query";
  required?: boolean;
  placeholder?: string;
};

export type ConnectorResourcePagination =
  | { kind: "page"; pageParam: string; sizeParam?: string }
  | { kind: "cursor"; cursorParam: string; sizeParam?: string }
  | { kind: "none" };

export type ConnectorResourceDetail = {
  path: string;
  idField: string;
  idParam: string;
  queryParams?: readonly string[];
};

export type ConnectorResource = {
  id: string;
  label: string;
  path: string;
  params: readonly ConnectorResourceParam[];
  pagination: ConnectorResourcePagination;
  shape: "items" | "item";
  columns: readonly string[];
  detail?: ConnectorResourceDetail;
};

export type ConnectorResourceCatalog = Record<string, readonly ConnectorResource[]>;

// These paths were checked against the GET routes in src/wait_local_agent/api/app.py
// (3416-4296). Keep this literal allowlist beside the catalog so a new UI route
// cannot be introduced without an explicit backend verification step.
export const VERIFIED_CONNECTOR_READ_ROUTES = [
  "/connectors/halopsa/tickets/{ticket_id}",
  "/connectors/halopsa/tickets/{ticket_id}/notes",
  "/connectors/halopsa/clients",
  "/connectors/halopsa/clients/{client_id}/assets",
  "/connectors/halopsa/categories",
  "/connectors/hudu/companies",
  "/connectors/hudu/articles",
  "/connectors/hudu/articles/{article_id}",
  "/connectors/hudu/folders",
  "/connectors/connectwise/tickets",
  "/connectors/connectwise/tickets/{ticket_id}",
  "/connectors/connectwise/companies",
  "/connectors/syncro/tickets",
  "/connectors/syncro/tickets/{ticket_id}",
  "/connectors/syncro/tickets/{ticket_id}/comments",
  "/connectors/syncro/customers",
  "/connectors/syncro/customers/{customer_id}",
  "/connectors/servicenow/incidents",
  "/connectors/servicenow/incidents/{sys_id}",
  "/connectors/servicenow/companies",
  "/connectors/servicenow/companies/{sys_id}",
  "/connectors/autotask/tickets",
  "/connectors/autotask/tickets/{ticket_id}",
  "/connectors/autotask/companies",
  "/connectors/autotask/companies/{company_id}",
  "/connectors/itglue/organizations",
  "/connectors/itglue/organizations/{organization_id}/documents",
  "/connectors/itglue/documents/{document_id}",
  "/connectors/itglue/organizations/{organization_id}/folders",
  "/connectors/confluence/pages",
  "/connectors/confluence/pages/{page_id}",
  "/connectors/notion/pages",
  "/connectors/notion/pages/{page_id}",
  "/connectors/notion/data-sources/{data_source_id}/pages",
  "/connectors/notion/data-sources/{data_source_id}",
  "/connectors/sharepoint/sites",
  "/connectors/sharepoint/sites/{site_id}",
  "/connectors/sharepoint/sites/{site_id}/documents",
  "/connectors/sharepoint/sites/{site_id}/documents/{item_id}",
  "/connectors/sharepoint/sites/{site_id}/documents/{item_id}/content",
  "/connectors/scalepad/clients",
  "/connectors/scalepad/risk-summaries",
  "/connectors/scalepad/compliance-health",
  "/connectors/scalepad/goals",
  "/connectors/scalepad/assessments",
  "/connectors/m365/users",
  "/connectors/m365/groups",
  "/connectors/m365/licenses",
  "/connectors/m365/users/license-details",
  "/connectors/m365/mail-folders",
  "/connectors/m365/mail-messages",
  "/connectors/m365/managed-devices",
  "/connectors/m365/teams",
  "/connectors/m365/teams/{team_id}/channels",
  "/connectors/m365/teams/{team_id}/channels/{channel_id}/messages"
] as const;

const queryParam = (name: string, label: string, placeholder?: string): ConnectorResourceParam => ({
  name,
  label,
  location: "query",
  placeholder
});

const pathParam = (name: string, label: string, placeholder?: string): ConnectorResourceParam => ({
  name,
  label,
  location: "path",
  required: true,
  placeholder
});

export const connectorResources: ConnectorResourceCatalog = {
  servicenow: [
    {
      id: "incidents",
      label: "Incidents",
      path: "/connectors/servicenow/incidents",
      params: [queryParam("query", "Search", "numberLIKEINC")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["sys_id", "number", "short_description", "state", "priority", "updated_at"],
      detail: { path: "/connectors/servicenow/incidents/{sys_id}", idField: "sys_id", idParam: "sys_id" }
    },
    {
      id: "companies",
      label: "Companies",
      path: "/connectors/servicenow/companies",
      params: [queryParam("query", "Search", "nameLIKEAcme")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["sys_id", "name", "number", "city", "country", "updated_at"],
      detail: { path: "/connectors/servicenow/companies/{sys_id}", idField: "sys_id", idParam: "sys_id" }
    }
  ],
  itglue: [
    {
      id: "organizations",
      label: "Organizations",
      path: "/connectors/itglue/organizations",
      params: [],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "organization_type", "status", "updated_at"]
    },
    {
      id: "documents",
      label: "Documents",
      path: "/connectors/itglue/organizations/{organization_id}/documents",
      params: [pathParam("organization_id", "Organization ID", "123"), queryParam("folder_id", "Folder ID")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "organization_id", "folder_id", "updated_at", "url"],
      detail: { path: "/connectors/itglue/documents/{document_id}", idField: "id", idParam: "document_id" }
    },
    {
      id: "folders",
      label: "Folders",
      path: "/connectors/itglue/organizations/{organization_id}/folders",
      params: [pathParam("organization_id", "Organization ID", "123")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "organization_id", "parent_folder_id"]
    }
  ],
  confluence: [
    {
      id: "pages",
      label: "Pages",
      path: "/connectors/confluence/pages",
      params: [queryParam("space_id", "Space ID"), queryParam("title", "Title")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "title", "space_id", "status", "web_url", "updated_at"],
      detail: { path: "/connectors/confluence/pages/{page_id}", idField: "id", idParam: "page_id" }
    }
  ],
  notion: [
    {
      id: "pages",
      label: "Pages",
      path: "/connectors/notion/pages",
      params: [queryParam("client_id", "Client ID", "acme"), queryParam("query", "Search")],
      pagination: { kind: "cursor", cursorParam: "start_cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "title", "url", "last_edited_time", "archived"],
      detail: { path: "/connectors/notion/pages/{page_id}", idField: "id", idParam: "page_id", queryParams: ["client_id"] }
    },
    {
      id: "data-source-pages",
      label: "Data-source pages",
      path: "/connectors/notion/data-sources/{data_source_id}/pages",
      params: [pathParam("data_source_id", "Data source ID", "00000000-0000-0000-0000-000000000000"), queryParam("client_id", "Client ID", "acme")],
      pagination: { kind: "cursor", cursorParam: "start_cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "title", "url", "last_edited_time", "archived"],
      detail: { path: "/connectors/notion/pages/{page_id}", idField: "id", idParam: "page_id", queryParams: ["client_id"] }
    },
    {
      id: "data-source",
      label: "Data source",
      path: "/connectors/notion/data-sources/{data_source_id}",
      params: [pathParam("data_source_id", "Data source ID", "00000000-0000-0000-0000-000000000000"), queryParam("client_id", "Client ID", "acme")],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "name", "url", "created_time", "last_edited_time"],
      detail: { path: "/connectors/notion/data-sources/{data_source_id}", idField: "id", idParam: "data_source_id", queryParams: ["client_id"] }
    }
  ],
  sharepoint: [
    {
      id: "sites",
      label: "Sites",
      path: "/connectors/sharepoint/sites",
      params: [],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "display_name", "web_url"],
      detail: { path: "/connectors/sharepoint/sites/{site_id}", idField: "id", idParam: "site_id" }
    },
    {
      id: "documents",
      label: "Documents",
      path: "/connectors/sharepoint/sites/{site_id}/documents",
      params: [pathParam("site_id", "Site ID", "site-id"), queryParam("parent_item_id", "Parent item ID")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "site_id", "parent_id", "size", "updated_at", "is_folder", "web_url"],
      detail: { path: "/connectors/sharepoint/sites/{site_id}/documents/{item_id}", idField: "id", idParam: "item_id" }
    },
    {
      id: "document-content",
      label: "Document content",
      path: "/connectors/sharepoint/sites/{site_id}/documents/{item_id}/content",
      params: [pathParam("site_id", "Site ID", "site-id"), pathParam("item_id", "Document ID", "item-id")],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "name", "content", "is_file", "web_url"]
    }
  ],
  syncro: [
    {
      id: "tickets",
      label: "Tickets",
      path: "/connectors/syncro/tickets",
      params: [queryParam("query", "Search"), queryParam("customer_id", "Customer ID"), queryParam("status", "Status"), queryParam("since_updated_at", "Updated since")],
      pagination: { kind: "page", pageParam: "page" },
      shape: "items",
      columns: ["id", "number", "subject", "status", "customer_name", "updated_at"],
      detail: { path: "/connectors/syncro/tickets/{ticket_id}", idField: "id", idParam: "ticket_id" }
    },
    {
      id: "ticket-comments",
      label: "Ticket comments",
      path: "/connectors/syncro/tickets/{ticket_id}/comments",
      params: [pathParam("ticket_id", "Ticket ID", "42")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "per_page" },
      shape: "items",
      columns: ["id", "ticket_id", "subject", "body", "tech", "created_at", "hidden"]
    },
    {
      id: "customers",
      label: "Customers",
      path: "/connectors/syncro/customers",
      params: [queryParam("query", "Search"), queryParam("business_name", "Business name")],
      pagination: { kind: "page", pageParam: "page" },
      shape: "items",
      columns: ["id", "business_name", "first_name", "last_name", "email", "phone"],
      detail: { path: "/connectors/syncro/customers/{customer_id}", idField: "id", idParam: "customer_id" }
    }
  ],
  halopsa: [
    {
      id: "ticket-notes",
      label: "Ticket notes",
      path: "/connectors/halopsa/tickets/{ticket_id}/notes",
      params: [pathParam("ticket_id", "Ticket ID", "123")],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "ticket_id", "body", "user_name", "created_at"]
    },
    {
      id: "clients",
      label: "Clients",
      path: "/connectors/halopsa/clients",
      params: [],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "status", "archived"]
    },
    {
      id: "client-assets",
      label: "Client assets",
      path: "/connectors/halopsa/clients/{client_id}/assets",
      params: [pathParam("client_id", "Client ID", "123")],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "name", "asset_type", "status"]
    },
    {
      id: "categories",
      label: "Categories",
      path: "/connectors/halopsa/categories",
      params: [],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "name", "parent_id"]
    }
  ],
  hudu: [
    {
      id: "articles",
      label: "Articles",
      path: "/connectors/hudu/articles",
      params: [queryParam("company_id", "Company ID")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "company_id", "folder_id", "updated_at", "url"],
      detail: { path: "/connectors/hudu/articles/{article_id}", idField: "id", idParam: "article_id" }
    },
    {
      id: "folders",
      label: "Folders",
      path: "/connectors/hudu/folders",
      params: [queryParam("company_id", "Company ID")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "company_id", "parent_folder_id"]
    },
    {
      id: "companies",
      label: "Companies",
      path: "/connectors/hudu/companies",
      params: [],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "archived"]
    }
  ],
  connectwise: [
    {
      id: "tickets",
      label: "Tickets",
      path: "/connectors/connectwise/tickets",
      params: [queryParam("conditions", "Conditions")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "summary", "status", "priority", "company", "lastUpdated"],
      detail: { path: "/connectors/connectwise/tickets/{ticket_id}", idField: "id", idParam: "ticket_id" }
    },
    {
      id: "companies",
      label: "Companies",
      path: "/connectors/connectwise/companies",
      params: [queryParam("conditions", "Conditions")],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "name", "identifier", "status", "city", "state"]
    }
  ],
  autotask: [
    {
      id: "tickets",
      label: "Tickets",
      path: "/connectors/autotask/tickets",
      params: [],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "external_id", "title", "status", "priority", "company_id"],
      detail: { path: "/connectors/autotask/tickets/{ticket_id}", idField: "id", idParam: "ticket_id" }
    },
    {
      id: "companies",
      label: "Companies",
      path: "/connectors/autotask/companies",
      params: [],
      pagination: { kind: "page", pageParam: "page", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "external_id", "name", "is_active", "city", "state"]
    }
  ],
  scalepad: [
    {
      id: "clients",
      label: "Clients",
      path: "/connectors/scalepad/clients",
      params: [],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "name", "lifecycle", "num_contacts", "num_hardware_assets", "record_updated_at"]
    },
    {
      id: "risk-summaries",
      label: "Risk summaries",
      path: "/connectors/scalepad/risk-summaries",
      params: [],
      pagination: { kind: "cursor", cursorParam: "cursor" },
      shape: "items",
      columns: ["client_id", "risk_score", "risk_level", "summary", "updated_at"]
    },
    {
      id: "compliance-health",
      label: "Compliance health",
      path: "/connectors/scalepad/compliance-health",
      params: [],
      pagination: { kind: "none" },
      shape: "item",
      columns: ["client_id", "health_score", "status", "controls_complete", "controls_total", "updated_at"]
    },
    {
      id: "goals",
      label: "Goals",
      path: "/connectors/scalepad/goals",
      params: [queryParam("status", "Status"), queryParam("title", "Title")],
      pagination: { kind: "cursor", cursorParam: "cursor" },
      shape: "items",
      columns: ["id", "title", "status", "due_date", "owner", "updated_at"]
    },
    {
      id: "assessments",
      label: "Assessments",
      path: "/connectors/scalepad/assessments",
      params: [queryParam("status", "Status"), queryParam("assessment_template_id", "Template ID")],
      pagination: { kind: "cursor", cursorParam: "cursor" },
      shape: "items",
      columns: ["id", "title", "status", "assessment_template_id", "completed_at", "updated_at"]
    }
  ],
  m365: [
    {
      id: "users",
      label: "Users",
      path: "/connectors/m365/users",
      params: [queryParam("identity", "Identity", "user@example.com")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "display_name", "user_principal_name", "mail", "account_enabled", "job_title", "department"]
    },
    {
      id: "groups",
      label: "Groups",
      path: "/connectors/m365/groups",
      params: [queryParam("identity", "Identity")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "display_name", "mail", "mail_nickname", "description", "security_enabled"]
    },
    {
      id: "licenses",
      label: "Licenses",
      path: "/connectors/m365/licenses",
      params: [],
      pagination: { kind: "cursor", cursorParam: "cursor" },
      shape: "items",
      columns: ["id", "sku_id", "sku_part_number", "capability_status", "applies_to", "consumed_units"]
    },
    {
      id: "license-details",
      label: "User license details",
      path: "/connectors/m365/users/license-details",
      params: [queryParam("identity", "Identity", "user@example.com")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "sku_id", "sku_part_number", "service_plans"]
    },
    {
      id: "mail-folders",
      label: "Mail folders",
      path: "/connectors/m365/mail-folders",
      params: [queryParam("identity", "Identity", "user@example.com")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "display_name", "parent_folder_id", "total_item_count", "unread_item_count"]
    },
    {
      id: "mail-messages",
      label: "Mail messages",
      path: "/connectors/m365/mail-messages",
      params: [queryParam("identity", "Identity", "user@example.com"), queryParam("folder_id", "Folder ID")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "subject", "sender_name", "sender_address", "received_date_time", "is_read", "has_attachments", "importance"]
    },
    {
      id: "managed-devices",
      label: "Managed devices",
      path: "/connectors/m365/managed-devices",
      params: [],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "device_name", "user_principal_name", "operating_system", "compliance_state", "last_sync_date_time", "manufacturer", "model"]
    },
    {
      id: "teams",
      label: "Teams",
      path: "/connectors/m365/teams",
      params: [],
      pagination: { kind: "none" },
      shape: "items",
      columns: ["id", "display_name", "description", "web_url"]
    },
    {
      id: "channels",
      label: "Team channels",
      path: "/connectors/m365/teams/{team_id}/channels",
      params: [pathParam("team_id", "Team ID", "team-id")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "team_id", "display_name", "description", "membership_type", "web_url"]
    },
    {
      id: "channel-messages",
      label: "Channel messages",
      path: "/connectors/m365/teams/{team_id}/channels/{channel_id}/messages",
      params: [pathParam("team_id", "Team ID", "team-id"), pathParam("channel_id", "Channel ID", "channel-id")],
      pagination: { kind: "cursor", cursorParam: "cursor", sizeParam: "page_size" },
      shape: "items",
      columns: ["id", "team_id", "channel_id", "subject", "body", "from_display_name", "created_at", "web_url"]
    }
  ]
};

export const connectorResourceHealthPaths = Object.keys(connectorResources).reduce<Record<string, string>>((paths, connectorId) => {
  paths[connectorId] = `/connectors/${connectorId}/health`;
  return paths;
}, {});

export function resourcesForConnector(connectorId: string): readonly ConnectorResource[] {
  return connectorResources[connectorId] ?? [];
}

// Used by tests and reviewers to ensure the catalog cannot drift into invented
// endpoints. Detail paths are checked as well as collection paths.
export function catalogPaths(): string[] {
  return Object.values(connectorResources).flatMap((resources) => resources.flatMap((resource) => [
    resource.path,
    ...(resource.detail ? [resource.detail.path] : [])
  ]));
}
