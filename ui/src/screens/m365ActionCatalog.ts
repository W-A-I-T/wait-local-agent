export type M365ActionCategory = "Identity" | "Licenses & Groups" | "Mailbox" | "Devices" | "Teams";

export type M365LookupKind = "users" | "groups" | "licenses" | "managed-devices" | "mail-folders" | "teams" | "channels";
export type M365LookupValue = "id" | "upn" | "sku_id";

export type M365ActionField = {
  name: string;
  label: string;
  type: "text" | "textarea" | "boolean" | "select" | "array" | "string-map";
  required?: boolean;
  default?: unknown;
  help?: string;
  options?: readonly { value: string; label: string }[];
  lookup?: {
    kind: M365LookupKind;
    value: M365LookupValue;
    dependsOn?: string;
  };
  vaultReference?: boolean;
};

export type M365ActionDefinition = {
  id: string;
  category: M365ActionCategory;
  title: string;
  description: string;
  endpoint: string;
  fields: readonly M365ActionField[];
};

const operationOptions = [
  { value: "add", label: "Add" },
  { value: "remove", label: "Remove" }
] as const;

const userIdentityField: M365ActionField = {
  name: "user_identity",
  label: "User (UPN or email)",
  type: "text",
  required: true,
  help: "Directory suggestions are optional; you can enter a UPN, email address, or user ID.",
  lookup: { kind: "users", value: "upn" }
};

const userIdField: M365ActionField = {
  name: "user_id",
  label: "User",
  type: "text",
  required: true,
  help: "Choose a directory suggestion or enter the user ID.",
  lookup: { kind: "users", value: "id" }
};

const deviceIdField: M365ActionField = {
  name: "device_id",
  label: "Managed device",
  type: "text",
  required: true,
  help: "Choose a device suggestion or enter the managed device ID.",
  lookup: { kind: "managed-devices", value: "id" }
};

const folderField = (name: string, label: string): M365ActionField => ({
  name,
  label,
  type: "text",
  required: true,
  help: "Choose a folder suggestion or enter the folder ID.",
  lookup: { kind: "mail-folders", value: "id" }
});

export const M365_ACTION_CATEGORIES: readonly M365ActionCategory[] = [
  "Identity",
  "Licenses & Groups",
  "Mailbox",
  "Devices",
  "Teams"
] as const;

export const M365_ACTION_CATALOG: readonly M365ActionDefinition[] = [
  {
    id: "create-user",
    category: "Identity",
    title: "Create user",
    description: "Queue a new Microsoft 365 user for approval.",
    endpoint: "/connectors/m365/users/drafts",
    fields: [
      {
        name: "user_principal_name",
        label: "User principal name",
        type: "text",
        required: true,
        help: "Enter the new user's sign-in address. Existing directory suggestions are optional.",
        lookup: { kind: "users", value: "upn" }
      },
      { name: "display_name", label: "Display name", type: "text", required: true },
      { name: "mail_nickname", label: "Mail nickname", type: "text", required: true },
      {
        name: "temporary_vault_name",
        label: "Vault secret name holding the temporary password",
        type: "text",
        required: true,
        help: "Name of the vault secret that holds the temporary password (min 14 chars). The password value itself is never entered here.",
        vaultReference: true
      },
      { name: "account_enabled", label: "Account enabled", type: "boolean", default: true },
      { name: "force_change_password_next_sign_in", label: "Force change password at next sign-in", type: "boolean", default: true }
    ]
  },
  {
    id: "disable-user",
    category: "Identity",
    title: "Offboard — Disable user",
    description: "Queue an offboarding action for approval.",
    endpoint: "/connectors/m365/users/disable-drafts",
    fields: [userIdentityField]
  },
  {
    id: "password-reset",
    category: "Identity",
    title: "Password reset",
    description: "Queue a password reset using a vault-held temporary password.",
    endpoint: "/connectors/m365/users/password-reset-drafts",
    fields: [
      userIdentityField,
      {
        name: "temporary_vault_name",
        label: "Vault secret name holding the temporary password",
        type: "text",
        required: true,
        help: "Name of the vault secret that holds the temporary password (min 14 chars). The password value itself is never entered here.",
        vaultReference: true
      },
      { name: "force_change_password_next_sign_in", label: "Force change password at next sign-in", type: "boolean", default: true },
      { name: "force_change_password_next_sign_in_with_mfa", label: "Force change password at next sign-in with MFA", type: "boolean", default: false }
    ]
  },
  {
    id: "authentication-method-removal",
    category: "Identity",
    title: "Remove authentication method",
    description: "Queue removal of one registered authentication method for approval.",
    endpoint: "/connectors/m365/users/authentication-method-drafts",
    fields: [
      userIdentityField,
      {
        name: "method_type",
        label: "Method type",
        type: "select",
        required: true,
        options: [
          { value: "fido2", label: "FIDO2" },
          { value: "microsoft_authenticator", label: "Microsoft Authenticator" },
          { value: "phone", label: "Phone" },
          { value: "software_oath", label: "Software OATH" }
        ]
      },
      { name: "method_id", label: "Authentication method ID", type: "text", required: true }
    ]
  },
  {
    id: "session-revocation",
    category: "Identity",
    title: "Revoke user sessions",
    description: "Queue revocation of a user's active sessions for approval.",
    endpoint: "/connectors/m365/users/session-revocation-drafts",
    fields: [userIdField]
  },
  {
    id: "license-change",
    category: "Licenses & Groups",
    title: "Change user licenses",
    description: "Queue adding or removing one or more license SKUs for approval.",
    endpoint: "/connectors/m365/users/license-drafts",
    fields: [
      userIdField,
      {
        name: "sku_ids",
        label: "License SKUs",
        type: "array",
        required: true,
        help: "Choose a license suggestion or enter the SKU ID.",
        lookup: { kind: "licenses", value: "sku_id" }
      },
      { name: "operation", label: "Operation", type: "select", required: true, options: operationOptions }
    ]
  },
  {
    id: "group-membership",
    category: "Licenses & Groups",
    title: "Change group membership",
    description: "Queue adding or removing a user from a group for approval.",
    endpoint: "/connectors/m365/groups/membership-drafts",
    fields: [
      {
        name: "group_id",
        label: "Group",
        type: "text",
        required: true,
        help: "Choose a group suggestion or enter the group ID.",
        lookup: { kind: "groups", value: "id" }
      },
      userIdField,
      { name: "operation", label: "Operation", type: "select", required: true, options: operationOptions }
    ]
  },
  {
    id: "mailbox-settings",
    category: "Mailbox",
    title: "Update mailbox settings",
    description: "Queue one or more mailbox setting changes for approval.",
    endpoint: "/connectors/m365/users/mailbox-settings-drafts",
    fields: [
      userIdentityField,
      {
        name: "settings",
        label: "Mailbox settings",
        type: "string-map",
        required: true,
        help: "Add setting names and their string values. At least one setting is required."
      }
    ]
  },
  {
    id: "move-message",
    category: "Mailbox",
    title: "Move mail message",
    description: "Queue moving a message between mailbox folders for approval.",
    endpoint: "/connectors/m365/mail-messages/move-drafts",
    fields: [
      userIdentityField,
      folderField("source_folder_id", "Source folder"),
      { name: "message_id", label: "Message ID", type: "text", required: true },
      folderField("destination_folder_id", "Destination folder")
    ]
  },
  {
    id: "delete-message",
    category: "Mailbox",
    title: "Delete mail message",
    description: "Queue deleting a message from a mailbox for approval.",
    endpoint: "/connectors/m365/mail-messages/delete-drafts",
    fields: [
      userIdentityField,
      folderField("source_folder_id", "Source folder"),
      { name: "message_id", label: "Message ID", type: "text", required: true }
    ]
  },
  {
    id: "read-state-message",
    category: "Mailbox",
    title: "Change mail read state",
    description: "Queue marking a message read or unread for approval.",
    endpoint: "/connectors/m365/mail-messages/read-state-drafts",
    fields: [
      userIdentityField,
      folderField("source_folder_id", "Source folder"),
      { name: "message_id", label: "Message ID", type: "text", required: true },
      { name: "is_read", label: "Mark as read", type: "boolean", default: true }
    ]
  },
  {
    id: "reboot-device",
    category: "Devices",
    title: "Reboot managed device",
    description: "Queue a managed-device reboot for approval.",
    endpoint: "/connectors/m365/managed-devices/reboot-drafts",
    fields: [deviceIdField]
  },
  {
    id: "remote-lock-device",
    category: "Devices",
    title: "Remote-lock managed device",
    description: "Queue a remote lock for a managed device for approval.",
    endpoint: "/connectors/m365/managed-devices/remote-lock-drafts",
    fields: [deviceIdField]
  },
  {
    id: "retire-device",
    category: "Devices",
    title: "Retire managed device",
    description: "Queue retiring a managed device for approval.",
    endpoint: "/connectors/m365/managed-devices/retire-drafts",
    fields: [deviceIdField]
  },
  {
    id: "sync-device",
    category: "Devices",
    title: "Sync managed device",
    description: "Queue an Intune sync for a managed device for approval.",
    endpoint: "/connectors/m365/managed-devices/sync-drafts",
    fields: [deviceIdField]
  },
  {
    id: "teams-message",
    category: "Teams",
    title: "Send Teams message",
    description: "Queue a Teams channel message for approval.",
    endpoint: "/connectors/m365/teams/message-drafts",
    fields: [
      {
        name: "team_id",
        label: "Team",
        type: "text",
        required: true,
        help: "Choose a team suggestion or enter the team ID.",
        lookup: { kind: "teams", value: "id" }
      },
      {
        name: "channel_id",
        label: "Channel",
        type: "text",
        required: true,
        help: "Choose a channel suggestion after selecting a team, or enter the channel ID.",
        lookup: { kind: "channels", value: "id", dependsOn: "team_id" }
      },
      { name: "body", label: "Message", type: "textarea", required: true, help: "The message remains an approval draft until an administrator executes it." }
    ]
  }
] as const;

export function defaultsForM365Action(action: M365ActionDefinition): Record<string, unknown> {
  return Object.fromEntries(action.fields.filter((field) => field.default !== undefined).map((field) => [field.name, field.default]));
}
