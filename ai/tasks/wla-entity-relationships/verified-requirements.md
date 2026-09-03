# Live-verified: entity relationships (OneToMany lookup)

Established against WAIT-Dev on 2026-09-02 by iterating real import failures, then cloning the
solution back to confirm the relationship exists. Four rounds; each error named exactly one
missing requirement.

## The four requirements, in the order Dataverse enforced them

1. **Every entity needs `<LocalizedCollectionNames>`**, not just `<LocalizedNames>`.
   Error: *"Entity Display Collection Name for id: ... objectcolumn: LocalizedCollectionName ...
   not specified"*

2. **A OneToMany relationship needs `<EntityRelationshipRoles>`** on the referencing side.
   Error: *"The entity relationship role of the referencing entity is required when creating a new
   one-to-many entity relationship"*

   Emitted:

       <EntityRelationshipRoles>
         <EntityRelationshipRole>
           <NavPaneDisplayOption>UseCollectionName</NavPaneDisplayOption>
           <NavPaneAreaDisplayOption>Details</NavPaneAreaDisplayOption>
           <NavPaneAreaOrder>10000</NavPaneAreaOrder>
           <NavigationPropertyName>wait_dept_employee</NavigationPropertyName>
           <RelationshipRoleType>1</RelationshipRoleType>
         </EntityRelationshipRole>
       </EntityRelationshipRoles>

3. **The referencing lookup attribute must actually exist** on the referencing entity, with a
   display name. Declaring `<ReferencingAttributeName>` is not enough.
   Error: *"Attribute Display Name for id: ... objectcolumn: DisplayName and labelTypeCode:
   Attribute not specified"*

       <attribute PhysicalName="wait_deptid">
         <Type>lookup</Type> ... <LookupStyle>single</LookupStyle><LookupTypes />
         <displaynames><displayname description="Dept" languagecode="1033" /></displaynames>
       </attribute>

4. **The relationship needs a root component entry** alongside both entities.
   `<RootComponent type="10" schemaName="wait_dept_employee" behavior="0" />`
   Type 10 was used and the import succeeded; it has not been independently corroborated, so
   treat the numeric code as observed-working rather than documented.

## Verified round-trip

Cloned back from the tenant, `wait_dept.xml` contains:

    EntityRelationshipType: OneToMany
    ReferencingEntityName:  wait_employee
    ReferencedEntityName:   wait_dept
    ReferencingAttributeName: wait_deptid
    CascadeDelete:          RemoveLink

Both entities exist, and the `wait_deptid` lookup column was created.

## Why this matters for the emitter

WAIT currently emits no `<EntityRelationships>` at all. A single-table design is unaffected, but
any design with a lookup will **pack cleanly and fail on import** - the silent-omission failure
mode Microsoft documents. Emitting a relationship requires all four items above together; emitting
a partial one is worse than emitting none, because the failure surfaces at import time in a
customer tenant rather than at build time.
