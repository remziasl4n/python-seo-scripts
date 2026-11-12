# Semantic SEO principles behind the tools

This is the design reference for every tool in the repo. It sets out what is known about how Google reads, groups and ranks content, what the semantic SEO framework (Holistic SEO / Koray Tuğberk GÜBÜR) adds on top, and exactly how each idea becomes something a script can measure.

When you build or change a tool, find the principle it implements here and follow the method described.

## Evidence levels

Not everything written about Google is equally solid. Every principle below is tagged:

| Tag | Meaning | How to treat it |
|---|---|---|
| **Google** | Stated in Google's documentation, sworn testimony, or the court opinions in *US v. Google* | Safe to build on |
| **Leak** | The attribute exists in the 2024 Content Warehouse API documentation. Weights and usage are unknown | Build *proxies*, never claim to compute the real signal |
| **Patent** | Google patented the method. It may or may not run in production | Useful model of how a system *could* work |
| **Framework** | Practitioner model from Holistic SEO, backed by case studies, not controlled tests | Useful for planning and writing; validate with your own data |

**Rule for all tools:** a metric inspired by a Leak or Patent item is a proxy. Name it as one (`site_radius_proxy`, not `site_radius`), and never present it as Google's score.

---

## 1. How Google reads and ranks content

### 1.1 Indexing: what gets stored

| What happens | Evidence | What a tool can measure |
|---|---|---|
| Google analyses page text plus key elements such as `<title>` and image `alt` | Google | Title, headings, alt text and main text are extracted separately for every page |
| Similar pages are **clustered**, and one page per cluster is chosen as the canonical. The others become alternates | Google | Near-duplicate detection; flag clusters where the canonical Google picks may not be the one you want |
| Signals are collected about the canonical: language, country, usability | Google | Language and hreflang checks, page experience data |
| Documents are indexed by **phrases**. A phrase is "good" if it predicts other phrases; two phrases are "related" when they co-occur far more often than chance | Patent (phrase-based indexing, Anna Patterson) | Co-occurrence analysis over the pages that rank for a topic (see `phrase-gap`) |
| Pages carry Knowledge Graph entity annotations | Leak (`EntityAnnotations`) | Entity extraction and salience via the Natural Language API |
| Pages and sites have embeddings. `siteRadius` is documented as "how far page_embeddings deviate from the site_embedding"; `siteFocusScore` as "how much a site is focused on one topic" | Leak | Embed every page, compute a site centroid, measure each page's distance (see `site-focus`) |
| An LLM-based effort estimate exists for article pages (`contentEffort`) | Leak | Originality and depth checks; never a claimed score |

**How the phrase patent defines relatedness**, which `phrase-gap` reproduces at small scale:

- **Candidate phrases:** take every 2–5-word window in a document.
- **Information gain** between phrases A and B is *actual* co-occurrence divided by *expected* co-occurrence. The expected rate comes from how many documents contain each phrase.
- **Thresholds:** a phrase is kept as "good" when it predicts other phrases with information gain above about 1.5 (the patent gives 1.1–1.7). It is "related" to another phrase when the gain is far higher; the patent's web-scale example threshold is 100.
- **Co-occurrence window:** counted within ±30 words.
- **What a document is about:** documents that contain many of a phrase's *related* phrases are treated as being about that phrase. Anchor text is weighted heavily (0.7 anchor vs 0.3 body in the example).

### 1.2 Ranking: how a result is chosen

| What happens | Evidence | What a tool can measure |
|---|---|---|
| **Topicality (T\*)** scores how relevant a document is to the query terms, built from **A**nchors, **B**ody and **C**licks | Google (DOJ trial testimony, HJ Kim) | Query terms in title/H1/headings/body; internal anchor text pointing at the page; clicks and CTR from GSC |
| **Quality (Q\*)** is a largely static, mostly hand-crafted site-level score using PageRank, content signals, spam scores and rater evaluations | Google (trial) | Not measurable directly. Proxies: thin content, duplicates, site focus |
| **Popularity (P\*)** uses Chrome visits, anchor counts and Navboost | Google (trial) | Only partly visible: GSC clicks, backlink tools |
| **Navboost** re-ranks using about 13 months of aggregated click data ("good", "bad", "last longest" clicks), split by country and device | Google (trial) | GSC CTR compared with the CTR expected for the position (`ctr-gap`) |
| **RankEmbed** is a dual-encoder model that embeds queries and documents in the same space | Google (trial) | Query-to-page and query-to-passage cosine similarity with Gemini embeddings |
| **Passage ranking** judges individual sections of a page | Google (ranking systems guide) | Split pages into passages and score each passage, not just the page |
| **BERT** reads how words combine; **neural matching** and **RankBrain** connect queries to concepts without exact words | Google | Semantic similarity, not just keyword matching |
| **Deduplication** shows only the most relevant of very similar results; **site diversity** usually limits a site to two results | Google | Cannibalization: two of your pages competing for the same query dilute each other |
| Most ranking signals are hand-crafted with engineer-set curves and thresholds | Google (trial) | Clear, explainable rules in our tools are a reasonable mirror |

### 1.3 AI Overviews and AI Mode

| What happens | Evidence | What a tool can measure |
|---|---|---|
| **Query fan-out**: "issuing multiple related searches across subtopics and data sources" | Google | Generate fan-out queries; capture the searches Gemini actually runs when grounded |
| Fan-out query types: related, implicit, comparative, recent, personalized, reformulation, entity-expanded | Patent (as analysed by iPullRank) | Generate each type separately so coverage gaps are visible by type |
| Passages, not pages, are retrieved and cited. An LLM compares passages in pairs to rank them | Patent | Passage-level relevance and self-containment checks |
| Citations go to the passages that best support each reasoning step, independently of page rank | Patent | Track which domains are cited; compare their passages with yours |
| "No additional requirements ... nor other special optimizations necessary." Pages must be indexed and snippet-eligible | Google | Indexing and snippet controls are part of the AI checks |
| An **information gain** score from 0 to 1 rates how much new information a document adds beyond documents already seen | Patent | Passage novelty compared with competing pages (`information-gain`) |

### 1.4 Tokenization and passages

Google does not publish how it splits pages into passages or which tokenizer each ranking system uses. What is known:

- BERT-family rankers read about 512 WordPiece tokens, query and passage combined. Long documents therefore have to be truncated or split into passages.
- `gemini-embedding-2` accepts 8,192 tokens and silently truncates anything longer. `gemini-embedding-001` accepts 2,048.

**What the tools do:**
- **Split by headings.** Pages become passages along heading boundaries: an H2 or H3 plus its content.
- **Cap the size.** An oversized section is split further at paragraph boundaries, so each passage stays in the low hundreds of words.
- **Count tokens.** Every passage records its token count.

This is an approximation that fits both passage ranking and passage-level AI retrieval. It also means a passage that only makes sense with the rest of the page is a weak passage.

---

## 2. The semantic SEO framework (Holistic SEO)

All items in this section are **Framework** level. These concepts organise planning and writing; the right-hand column says how a tool makes each one concrete.

### 2.1 Site-level concepts

| Concept | Meaning | How the tools use it |
|---|---|---|
| **Source context** | Why the site exists and how it makes money. It decides which attributes the site should cover and which to skip | `source_context` field in `config/sites/<site>.yaml`, included in every planning prompt |
| **Central entity** | The entity that appears across every section of the site | `central_entity` in site config. `site-focus` checks it appears in titles and H1s |
| **Central search intent** | Source context + central entity combined | Used to classify every planned page as core or outer |
| **Core section** | Pages about the central entity's main attribute, the one tied to the source context | `topical-map` labels nodes `core` |
| **Outer section** | Pages about minor attributes. They build trust and pass relevance to the core | `topical-map` labels nodes `outer` and links them to core nodes |
| **Topical map** | The structured plan built from the five items above | Output of `topical-map` |
| **Semantic content network** | The connected set of pages that implements the map. Weak pages can drag strong ones down | `site-focus` and `content-audit` flag weak or off-topic nodes |
| **Topical coverage** | How completely the site defines and connects the subject. Page count alone doesn't measure it | `topical-map` marks each node covered, partly covered or missing |
| **Contextual bridge** | A connection between two nodes of the map, made with a link or with consistent information | `internal-links` lists links between clusters and suggests missing bridges |
| **Momentum** | How often the site publishes and updates. It affects crawl and ranking speed | `topic-performance` tracks pages published and updated per cluster per month |
| **Ranking signal dilution** | Two pages competing for the same canonical query and intent | `cannibalization` |

### 2.2 Entities and queries

| Concept | Meaning | How the tools use it |
|---|---|---|
| **Entity–attribute–value (EAV)** | Describe each entity through its attributes and their values. Values need the right type and unit | `entity-attributes` builds the attribute list; `page-structure` checks values are stated with units and numbers |
| **Attribute prominence, popularity, relevance** | How defining an attribute is, how much it's searched, and how well it fits the source context | Scored per attribute in `entity-attributes` |
| **Root / rare / unique attributes** | Shared by every entity of the type / by few / by this entity only | Computed by comparing the entity's attributes with sibling entities of the same type |
| **Attribute importance shifts with context** | "Population" keeps a page about a city; "population problems" moves it into another topic | Attributes are scored against the site's source context, not in isolation |
| **Query network** | All the ways a topic is searched: aspects, definitions, comparisons | Output of `query-fanout` |
| **Query templates** | Repeatable patterns: "what is X", "X vs Y", "best X for Y", "how to X", "X cost" | `query-fanout` and `topical-map` apply templates to every entity and attribute |
| **Representative query** | A broad query that can draw on the relevance of more specific ones | Each cluster gets a representative query: the most-searched member, or the one nearest the cluster centre |
| **Lexical relations** | Synonyms, antonyms, hypernyms (broader), hyponyms (narrower), meronyms (part of), holonyms (whole of) | `query-fanout` and `entity-attributes` ask for each relation type explicitly |

### 2.3 Page-level concepts

| Concept | Meaning | How the tools use it |
|---|---|---|
| **Macro context** | The one main topic of a page, carried by the title, H1, introduction and main content | `page-structure` checks title, H1, intro and conclusion all embed close to each other |
| **Micro context** | Sub-topics inside the page, usually one per section | Each H2 is checked for similarity to the H1: related, but not a repeat |
| **Contextual flow** | The order in which a page moves through its contexts | Similarity between consecutive sections; sudden jumps are flagged |
| **Contextual coverage** | How much of the page each context takes up. Over-covering one weakens the others | Token share per section |
| **Contextual border** | Where main content ends and supplementary content (sidebars, CTAs, related links) begins | Main-content extraction; share of text that is boilerplate; CTAs placed between a question and its answer |
| **Contextual vector** | The vocabulary a topic is expected to use | `phrase-gap` compares your vocabulary with the pages that rank |
| **Information responsiveness** | Whether the page meets every need behind the query | `fanout-coverage` |

### 2.4 Writing rules a script can check

These come from the semantic writing rules taught in the framework. A script can check these reliably:

- **Question headings:** headings are short questions where the intent is a question.
- **Answer first:** the first sentence under a heading answers it, and repeats the heading's main terms.
- **Answer length:** direct answers are about 40 words (around 320 characters).
- **Precise wording:** vague quantifiers ("many", "several", "a lot of") get flagged. Numbers, dates and named sources are counted.
- **Core terms in key places:** the core terms appear in the title, H1, introduction and conclusion.
- **Correct list types:** ordered lists are used for sequences, unordered lists for sets.
- **Anchor text:** internal links use anchor text that matches the target page's title or H1.
- **Clean answers:** no CTA sits between a question heading and its answer.
- **Schema matches the page:** structured data matches the visible content.
- **Authorship:** author, date and reviewer are present where the topic needs them.
- **Distinct pages:** page-to-page similarity stays low across the site.

---

## 3. Design rules every tool follows

1. **Measure passages, not only pages.** Ranking and AI retrieval both work on passages, so any content tool reports results per passage as well as per page.
2. **Entities and attributes, not just keywords.** Where it makes sense, outputs carry `entity` and `attribute` columns so results roll up into the topical map.
3. **Group the way Google groups.**
   - **With SERP data:** pages that share top-10 results serve the same intent. The default is 3 of 10 shared URLs, and it's configurable.
   - **Without SERP data:** embedding similarity is the cheaper stand-in.
   - **Labelling:** the output says which method was used.
4. **Real data beats model guesses.** Every query or attribute a model generates gets `source` and `evidence` columns: Gemini, Gemini's own grounded searches, autocomplete, GSC impressions or search volume. Sorting by evidence is always possible.
5. **Proxies are labelled as proxies.** See [Evidence levels](#evidence-levels).
6. **The site's context drives every plan.** Source context, central entity, brand terms and competitors come from the site config, so the same tool gives different plans for different sites.
7. **Compare like with like.** Scores are only comparable when made with the same embedding model and settings. Outputs record the model used, and comparisons refuse to mix models.
8. **Use the right embedding task.** Queries use the search-query format and passages use the document format, so passage relevance is retrieval. Keyword grouping uses the clustering format.
9. **Explainable over clever.** Following Google's own hand-crafted approach, scores are built from a few named parts. Each part is shown in the output, so you can see why something scored low.

---

## 4. Tool catalog

★ = first wave. "Needs" lists the minimum setup; everything else is optional enrichment.

### Research

**`query-fanout` ★**: the query network for a query or entity
- *Principles:* query fan-out (Google), fan-out types (Patent), query templates and lexical relations (Framework)
- *Method:*
  1. Gemini generates queries for each fan-out type it can simulate (related, implicit, comparative, reformulation, entity-expanded), applies the query templates, and adds lexical relations.
  2. A grounded Gemini call records the searches Gemini actually runs (`source = gemini-search`).
  3. Every query is checked against autocomplete and, if connected, GSC impressions.
  4. Near-identical rewordings are merged by embedding similarity.
- *Output:* query, fan-out type, intent, entity, attribute, sources, autocomplete hit, GSC impressions
- *Needs:* Gemini key

**`autocomplete` ★**: what people actually type
- *Method:* Google Suggest for the seed, the seed + a–z, and question and preposition modifiers. Results are deduped and lightly cleaned. This is the cheapest real-demand signal and is reused by most research tools.
- *Needs:* nothing

**`entity-attributes` ★**: which attributes of an entity to cover, and in what order
- *Principles:* EAV, attribute prominence/popularity/relevance, root/rare/unique (Framework)
- *Method:*
  1. Gemini lists the entity's attributes, and the attributes of 5–10 sibling entities of the same type. The Knowledge Graph API supplies the type where available.
  2. **Class:** root = shared by most siblings, rare = by few, unique = this entity only.
  3. **Prominence:** how often the attribute shows up in autocomplete and fan-out queries.
  4. **Relevance:** embedding similarity to the site's source context.
  5. **Placement:** each attribute is labelled core or outer, with the query templates that apply to it.
- *Output:* attribute, class, value type and unit, prominence, relevance, priority, core/outer, example queries
- *Needs:* Gemini key

**`keyword-clusters` ★**: group a keyword list into topics
- *Principles:* Google clusters similar results; representative query
- *Method:*
  - **Grouping:** SERP overlap when a SERP API is configured, otherwise Gemini embeddings (clustering task).
  - **Naming:** each cluster gets a representative query (most impressions, else nearest the centre) and an intent label.
- *Output:* keyword, cluster, representative query, intent, method used
- *Needs:* Gemini key (SERP API optional)

**`intent`**: labels each keyword as informational, commercial, transactional or navigational, plus funnel stage and the page type it needs. *Needs:* Gemini key

### Content

**`page-structure`**: a semantic audit of one page or a list of URLs
- *Principles:* macro/micro context, contextual flow, coverage and border, writing rules (Framework); passage ranking (Google)
- *Method:*
  1. Extract the main content and split it into passages.
  2. Check that title, H1, intro and conclusion carry the same context.
  3. Check that each H2 is related to the H1 without repeating it, and that consecutive sections flow.
  4. Run the [writing rules](#24-writing-rules-a-script-can-check).
- *Output:* one row per check with pass/flag and the exact passage that caused it
- *Needs:* nothing (Gemini key for the similarity checks)

**`phrase-gap`**: vocabulary the ranking pages share that yours lacks
- *Principles:* phrase-based indexing (Patent), contextual vector (Framework)
- *Method:*
  1. Build a corpus from the top-ranking pages for a query. They come from the SERP API, or you supply the URLs.
  2. Extract 2–5-word phrases.
  3. Compute information gain (actual ÷ expected co-occurrence within ±30 words) to find the phrases that predict the topic.
  4. Compare with your page.
- *Output:* phrase, how many ranking pages use it, information gain, present on your page?
- *Needs:* nothing if you supply URLs

**`information-gain`**: what your page adds beyond the pages that already rank
- *Principles:* information gain score (Patent)
- *Method:*
  1. Embed your passages and the competitors' passages.
  2. Each of your passages gets novelty = 1 − its highest similarity to any competitor passage.
  3. The page score is the share of passages above a novelty threshold.
- *Output:* per-passage novelty, page score, competitor topics you don't cover
- *Needs:* Gemini key

**`entity-salience`**: whether the page is clearly about what you think it's about. Natural Language API entities and salience for your page and competitors. Flags when the central entity isn't the most salient entity, or when key entities are missing. *Needs:* Google API key

**`content-brief`**: combines `query-fanout`, `entity-attributes`, `phrase-gap` and `page-structure` rules into a writer's brief: macro context, H2 outline ordered for contextual flow, attributes with value types, questions with answer formats, and internal links to add. *Needs:* Gemini key

**`titles`**: new titles and meta descriptions for `ctr-gap` pages, built from the queries each page already gets impressions for (the Clicks and Body signals in Topicality). *Needs:* GSC + Gemini

**`link-suggestions`**: pages to link from and to for a given page, with anchor text matching the target's title or H1. *Needs:* Gemini key + crawl

**`content-audit`**: every page's traffic, trend, focus distance, duplicates and links, with a keep / update / merge / remove recommendation. *Needs:* GSC + crawl

### Performance (Search Console / GA4)

| Tool | Principle | Method |
|---|---|---|
| `striking-distance` ★ | Topicality on queries you're close to | Queries at positions 4–20 with impressions, grouped by page |
| `ctr-gap` ★ | Navboost (Google) | The site's own CTR curve by position; pages and queries well below expected are flagged |
| `content-decay` ★ | Re-ranking over time | Clicks per page between two periods, with the queries that drove the change |
| `cannibalization` ★ | Dilution (Framework), deduplication and site diversity (Google) | Queries where several of your URLs share impressions; content similarity between those URLs decides merge or differentiate |
| `topic-performance` | Topical coverage and momentum (Framework) | GSC aggregated by topic cluster: queries, clicks and positions per cluster over time, plus pages published and updated |
| `brand-split` | | Brand vs non-brand trend using brand terms from site config |
| `update-impact` | | Before and after a date, by folder, cluster and query |
| `landing-pages` | | GSC joined with GA4 engagement and conversions |

### Technical

| Tool | Principle | Method |
|---|---|---|
| `site-focus` ★ | `siteFocusScore` and `siteRadius` (Leak), central entity (Framework) | Embed every indexable page and compute the site centroid. Each page gets a distance proxy; the site and each section get a focus proxy. Off-topic pages are listed |
| `crawl` | Indexing elements (Google) | Status, title, meta, H1–H3, canonical, word and token counts, main-content share, near-duplicate clusters |
| `sitemap-audit` | | Status, canonical and noindex for every sitemap URL |
| `index-status` | Canonical selection (Google) | URL Inspection API: Google's verdict and chosen canonical against yours |
| `internal-links` | Anchors in Topicality (Google), contextual bridges (Framework) | Link graph, orphans, click depth, anchor-vs-target-title match, links between clusters and core↔outer |
| `core-web-vitals` | Page experience | PageSpeed Insights / CrUX for a URL list |
| `redirect-map` | | Match old URLs to new by URL and content similarity |

### Planning

**`topical-map`**: the full plan for a subject
- *Principles:* every Framework concept in section 2
- *Method:*
  1. Start from the site config: source context and central entity.
  2. `entity-attributes` gives the attributes with their core/outer labels.
  3. `query-fanout` and query templates run for each attribute.
  4. `keyword-clusters` groups the results into nodes.
  5. Each node gets a page type, representative query, outline and contextual bridges.
  6. Existing coverage is marked from crawl and GSC data.
  7. Nodes are ordered so foundational nodes come before the pages that depend on them, weighted by demand.
- *Output:* a spreadsheet of nodes plus a diagram of the map

**`prioritize`**: ranks opportunities from any tool by potential traffic, how close you already are, and effort.

**`forecast`**: estimated clicks if target queries reach a given position, using the site's own CTR curve.

### AI search

**`fanout-coverage` ★**: how well your page answers everything behind a query
- *Principles:* query fan-out (Google), passage retrieval (Patent), information responsiveness (Framework)
- *Method:*
  1. Run `query-fanout` for the target query.
  2. Split your page into passages.
  3. Embed queries as search queries and passages as documents.
  4. For each fan-out query, find the best-matching passage and its score.
  5. Flag passages that don't stand alone (they open with "this", "it" or "they", or point to other sections).
- *Output:* fan-out query, best passage, score, covered/partial/missing; overall coverage by fan-out type
- *Needs:* Gemini key

**`ai-visibility`**: runs a fixed set of prompts through grounded Gemini and records whether your brand or domain is mentioned or cited, and who is instead. Rerun it to track changes.

**`citation-sources`**: which domains grounded answers cite for a topic. These are the pages whose passages to study.

---

## 5. What this means for the foundations

**Shared code the tools need:**
- **`connectors/gemini.py`:**
  - structured JSON output
  - grounding with Google Search, returning the searches the model ran
  - embeddings with the search-query, document and clustering task formats
  - batching and caching
  - model names read from config (they change often)
- **`lib/passages.py`:** main-content extraction, heading-based passage splitting, token counts
- **`lib/vectors.py`:** cosine similarity, centroids, nearest neighbours, clustering, a novelty score
- **`lib/phrases.py`:** n-grams, co-occurrence within a window, information gain
- **`lib/text_rules.py`:** the writing-rule checks
- **Site config fields:** `source_context`, `central_entity`, `entity_type`, `brand_terms`, `competitors`, `country`, `language`

**Dependencies to add:**
- `google-genai`: Gemini.
- `trafilatura`: main vs supplementary content.
- `google-cloud-language`: entity salience; optional.
- `spacy`: lemmas, sentences and noun phrases for better phrase statistics; optional.

---

## Sources

**Google**
- [How Google Search works](https://developers.google.com/search/docs/fundamentals/how-search-works): crawling, indexing, clustering and canonicals
- [A guide to Google Search ranking systems](https://developers.google.com/search/docs/appearance/ranking-systems-guide)
- [AI features and your website](https://developers.google.com/search/docs/appearance/ai-features): query fan-out, eligibility
- [Gemini API: Grounding with Google Search](https://aistudio.google.com/docs/google-search) and [Embeddings](https://aistudio.google.com/docs/embeddings)
- [Cloud Natural Language API basics](https://docs.cloud.google.com/natural-language/docs/basics)

**Trial and leak (secondary summaries; primary documents are the court opinions in Case 1:20-cv-03010)**
- [How Google works: DOJ trial disclosures](https://www.hobo-web.co.uk/how-google-works/), Hobo
- [Topical authority: siteRadius and siteFocusScore](https://www.hobo-web.co.uk/topical-authority/), Hobo
- [2024 Google Search documentation leak](https://en.wikipedia.org/wiki/2024_Google_Search_documentation_leak), Wikipedia
- [Unpacking Google's massive search documentation leak](https://searchengineland.com/unpacking-googles-massive-search-documentation-leak-442716), Search Engine Land

**Patents**
- [Phrase-based searching in an information retrieval system (US9990421B2)](https://patents.google.com/patent/US9990421B2/en)
- Contextual estimation of link information gain (US 11,354,342 B2); see [Search Engine Journal's summary](https://www.searchenginejournal.com/googles-information-gain-patent-for-ranking-web-pages/524464/)
- AI Mode patents as analysed in [How AI Mode works](https://ipullrank.com/how-ai-mode-works), iPullRank

**Semantic SEO framework**
- [What is Topical Authority?](https://www.holisticseo.digital/theoretical-seo/topical-authority/), Holistic SEO
- [How to expand a topical map](https://www.holisticseo.digital/seo-research-study/topical-map), Holistic SEO
- [Entity, Attribute, Value architecture](https://www.holisticseo.digital/seo-research-study/entity-attribute-value), Holistic SEO
- [Lexical semantics and semantic similarity](https://www.holisticseo.digital/seo-research-study/lexical-semantics), Holistic SEO
- [How does Google rank search results](https://www.holisticseo.digital/theoretical-seo/ranking/), Holistic SEO
- [Semantic SEO glossary](https://rokonz.com/resources/semantic-seo-glossary): definitions of source context, core/outer section, contextual terms
- [50 semantic content writing rules](https://uppleadseo.com/semantic-seo/content-writing-rules/)
- [SERP-overlap clustering thresholds](https://blog.hubspot.com/marketing/keyword-clustering), HubSpot
