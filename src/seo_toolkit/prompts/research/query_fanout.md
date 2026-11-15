You are planning content for a website. Expand the seed query into the searches Google's AI Mode would run to answer it completely (query fan-out).

## The website
- Domain: $domain
- Why it exists and how it makes money (source context): $source_context
- Central entity: $central_entity ($entity_type)
- Audience: country $country, language $language

## Seed query
"$query"

## Write $per_type queries for EACH fan-out type
- related: adjacent subtopics someone researching the seed also needs.
- implicit: needs the searcher didn't state but has (requirements, risks, timing, maintenance, follow-up decisions).
- comparative: choices between options, materials, brands or alternatives ("x vs y", "best x for y", "x or y").
- reformulation: the same need, worded the way different people type it (shorter, longer, other words).
- entity_expanded: the seed with its main entity swapped for a broader, narrower, part-of, whole-of or synonymous entity. Set lexical_relation to say which.
- template: query templates applied to the main entity and its attributes ("what is", "how to", "cost", "types of", "best", "pros and cons", "near me").

## Rules
- Write each query the way people type into Google: lowercase, no punctuation, usually 2 to 8 words, in language "$language".
- Every query must be relevant to the seed and worth covering given the source context. Leave out queries the site has no reason to answer.
- No duplicates, and no near-identical rewordings outside the reformulation type.
- For each query give:
  - entity: the main entity the query is about
  - attribute: the aspect of that entity it asks about (e.g. cost, size, materials, installation); empty if none
  - intent: informational, commercial, transactional or navigational
  - lexical_relation: for entity_expanded, how the new entity relates to the seed's (synonym, hypernym = broader, hyponym = narrower, meronym = part of, holonym = whole of, related_entity); otherwise none
  - rationale: why a searcher needs this, in under 15 words
