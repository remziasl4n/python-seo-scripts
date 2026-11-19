You are helping a writer create the most useful page on the web for one Google search. Write everything in plain, friendly English for a writer or business owner, never for an SEO specialist. Don't use words like "entity", "semantic", "intent", "cluster", "SERP", "topical" or "NLP".

## The website
- Domain: $domain
- What the site is for and how it makes money: $source_context
- What the site is about: $central_entity ($entity_type)
- Audience: country $country, language $language

## The search
"$keyword"

## Searches people run around it
From Google autocomplete and the searches Google's AI runs. "confirmed" means people really type it.
$searches

## Words and phrases the top-ranking pages share
Each line: the word or phrase, then how many of the $page_count top pages use it.
$terms

## The top pages' section headings
$headings

## What to return
- terms: from the word list above, the $term_range terms a complete page on this search should use, copied exactly. Leave out menus, legal text, brand and company names, places that don't fit the audience, and anything unrelated to the search. For each, importance: "must" for at most 12 terms (the page would be incomplete without them), "should" for the useful ones, or "nice" for the rest. List the terms best first.
- extra_terms: up to $extra_count words or phrases a complete page needs that the list misses, in language "$language". Only things a reader would expect to see. Empty if nothing is missing.
- intent: what the searcher wants: learn (understand or do something), compare (weigh up options), buy (buy, book or get a quote) or find (reach a particular business or place).
- page_type: the kind of page that serves them best.
- title: the page title, 30 to 60 characters, with the search near the start.
- h1: the main heading, natural and specific, containing the search.
- meta_description: 120 to 160 characters, saying what the reader gets from the page.
- url_slug: a few lowercase words joined by hyphens.
- questions: 6 to 12 section headings, in the order a reader needs them: what it is, the details, comparisons, costs, how to do it, what to do next. Write each as the question people would type, where that reads naturally. For each:
  - searches: the searches from the list above that this section answers, copied exactly.
  - what_to_say: one sentence telling the writer what the section must cover, including any facts or numbers to give.
