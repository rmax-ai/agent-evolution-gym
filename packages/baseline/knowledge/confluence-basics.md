# Confluence Basics

## Core concepts

- A Confluence site contains spaces, and a space groups pages around a team,
  product, or other area of work.
- A page has a stable identifier, a title, a body, and a space association.
- The page identifier is distinct from the title. Titles are useful for people,
  while identifiers are the reliable reference for API operations.
- A page may also have an owner and access rules. Visibility and editability are
  separate concerns: being able to read a page does not necessarily allow edits.
- Page content can include ordinary text, structured markup, links, and other
  presentation details. Treat content that is not being changed as meaningful.

## Versions

- A page has a current version represented by an integer revision number.
- The initial page is version 1. A successful edit creates a new version rather
  than replacing the historical record.
- Version history is ordered from the initial version through the current version.
  Earlier versions are immutable records of what was published at that revision.
- Updates use optimistic concurrency. The client supplies the version it read as
  a precondition for the write.
- If the supplied version is not the current version, the service can reject the
  write as a conflict. A conflict means the page should be read again before a
  later decision about its content is made.

## Search and retrieval

- Page search can match readable pages using page identifiers, space identifiers,
  titles, or body text.
- Search matching is case-insensitive in the simulator, and results are limited
  and offset for pagination.
- Search results contain page records rather than only titles, so the returned
  identifier and space can be used to distinguish similarly named pages.
- Search visibility follows the current actor's read permissions. An inaccessible
  page should not be assumed to be absent from the underlying site.
- A page retrieval returns the current representation. Version-history retrieval
  returns the immutable representations associated with each revision.

## API representation

- The raw service represents pages and collections as JSON objects and arrays.
- Create requests identify the new page, its space, and its initial content.
- Update requests contain only mutable page fields and the version precondition.
- Authentication identifies the acting user on each request; authorization is
  evaluated by the service for the requested page or space.

