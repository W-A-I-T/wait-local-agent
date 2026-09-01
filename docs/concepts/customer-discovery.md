# Customer discovery

WAIT can retrieve organizations from active PSA connector instances and place
them in the Client discovery review queue. This first slice is PSA-first:
HaloPSA, ConnectWise, Autotask, Syncro, and ServiceNow use their existing
read-only organization listing methods.

Discovery is deliberately deterministic. An existing verified connector
mapping wins; otherwise WAIT compares a case-folded name after removing
punctuation and the legal suffixes `Ltd`, `Inc`, `LLC`, and `GmbH`. One exact
client match becomes a proposed match. Multiple matches are ambiguous, and a
verified external ID conflict is conflicting. WAIT does not use fuzzy or AI
matching and does not silently create clients.

Administrators may accept a proposed match, create a new client from a
candidate, or dismiss it. Ambiguous and conflicting candidates cannot be bulk
accepted. Every activation, dismissal, discovery run, and deployment-mode
change is audited. Demo mode refuses discovery mutations.

The deployment mode is stored as `deployment.mode` in appliance configuration.
MSP mode exposes the review workflow; SMB mode keeps the existing manual client
setup flow and hides discovery from the user-facing screen.
