You are helping a website owner plan pages from a keyword list. The keywords have already been grouped: each group below becomes ONE page. Write the plan in plain, friendly English for a business owner or writer, never for an SEO specialist. Don't use words like "entity", "semantic", "intent", "cluster", "SERP" or "topical".

## The website
- Domain: $domain
- What the site is for and how it makes money: $source_context
- What the site is about: $central_entity ($entity_type)
- Audience: country $country, language $language
- Site sections (path, name, role): $sections
  (core sections sell or explain the main offer; outer sections support it)

## The pages to plan
Each page has an id, its main keyword, and its other keywords.
$pages

## For each page, give
- page: the page id, unchanged.
- main_keyword: the keyword from this page's own list (its main keyword or one of the others) that best sums up the whole page: usually the broadest, most natural wording.
- same_as: if this page would answer the same main question as another page listed here, that page's id. Otherwise leave it empty. Two pages for one question compete with each other in Google, so they will be merged.
- page_name: 2 to 5 plain words naming the page, e.g. "Inground pool costs".
- intent: what the searcher wants: learn (understand or do something), compare (weigh up options), buy (buy, book or get a quote) or find (reach a particular business or place).
- page_type: the kind of page that serves that best.
- section: the path of the site section the page belongs under, copied exactly from the list above, or "new" if none fits.
- url_slug: lowercase words joined by hyphens, based on the main keyword, without the section path.
- title: under 60 characters, starting with the main keyword or a close natural wording of it.
- h1: the main heading, natural and specific, containing the main keyword.
- meta_description: under 155 characters, saying what the reader gets from the page.
- keywords: EVERY other keyword of the page, in the order a reader would want them covered: what it is, the details, comparisons, costs, how to do it, what to do next. For each:
  - use_as: "heading" if it deserves its own section, or "text" if it should just be mentioned.
  - heading: for headings, the section heading written as the question people would type, e.g. "How much does an inground pool cost in Texas?". Several keywords that ask the same thing should share one heading, written identically.
- split_advice: leave empty unless the keywords on this page clearly want different things (for example some want to learn and others want to buy). Then say in one plain sentence how to split it.
