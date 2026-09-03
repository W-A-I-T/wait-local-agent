# Attribute mapping implementation note

A real `pac solution clone` export places entities in
`src/Entities/<logical>/Entity.xml` rather than inline in
`Other/Customizations.xml`. WAIT's inline form imports successfully, so no
change is being made for that layout difference. Do not compare a Dataverse
export to WAIT's output and report the normalised layout as a defect.
