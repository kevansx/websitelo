# The blog

## Where it came from

`/blog/` was a WordPress install on the old PHP host. When the site was cut over
that host stopped serving it, and 576 archived `/blog/` URLs — 115 of them real
posts — started returning 404. They were 71% of everything the old site had
indexed, and they are the long-tail content that brings people in.

Rather than rebuild WordPress, the content was recovered from the Internet
Archive and is now served by this app at exactly the URLs WordPress used. No URL
changed, so nothing had to be redirected and nothing lost its history.

## How it works

| Piece | What it does |
| --- | --- |
| `content/blog/<slug>.json` | One file per post: the content itself |
| `static/blog/uploads/**` | The post images, at their original paths |
| `blog_content.py` | Loads the files and indexes them by slug, category, tag and date |
| `templates/blog_index.html`, `templates/blog_post.html` | The listing and the post page |
| `static/brands/lottoexpress/css/blog.css` | Styling, including the WordPress block classes the recovered bodies use |
| `tools/blog_harvest.py` | The one-off recovery tool (see below) |

Posts are read from disk and cached in memory. The cache is keyed on how many
JSON files there are and when one last changed, so **adding or editing a post
takes effect without a restart** — which is what makes plain files a workable way
to publish.

## URLs served

Everything WordPress published, unchanged:

- `/blog/` and `/blog/page/<n>/` — the index, ten posts a page
- `/blog/<slug>/` — a post
- `/blog/category/<term>/` and `/blog/tag/<term>/`, both paginated
- `/blog/feed/` — RSS 2.0
- `/blog/wp-content/uploads/...` — the images

And the loose ends the old plugins left indexed:

- `/blog/<slug>/embed/`, `/q_glossy`, `/ret_img` — 301 to the page they belong to
- `/blog/wp-json/*`, `/blog/xmlrpc.php`, `/blog/wp-login.php`, `/blog/comments/feed/` — 410 Gone, deliberately
- A category or tag that no longer exists — 301 to `/blog/`
- A page number past the end — 301 to page one, rather than a dead end

## Writing a new post

Create `content/blog/<slug>.json`. The slug is the URL: `my-new-post.json` is
served at `/blog/my-new-post/`. Only `slug`, `title` and `body_html` are
required, but fill in the rest — the description and dates are what search
engines show.

```json
{
 "slug": "euromillions-jackpot-hits-200-million",
 "title": "EuroMillions Jackpot Hits €200 Million | Lotto Express",
 "heading": "EuroMillions Jackpot Hits €200 Million",
 "description": "The EuroMillions jackpot has rolled to its €200 million cap. Here is when the draw takes place and how to enter from anywhere.",
 "published": "2026-09-01T09:00:00+00:00",
 "modified": "2026-09-01T09:00:00+00:00",
 "author": "Lotto Express Marketing",
 "categories": ["Jackpot Alert"],
 "tags": ["Euromillions", "jackpot update"],
 "hero_image": "/blog/wp-content/uploads/2026/09/euromillions-200m.jpg",
 "word_count": 420,
 "body_html": "<p>The EuroMillions jackpot has reached its cap…</p>"
}
```

Notes that matter:

- **`title` is the `<title>` tag; `heading` is the `<h1>`.** They are allowed to
  differ, and on the recovered posts they usually do — the title carries the
  keywords, the heading reads better on the page.
- **`categories` and `tags` are display names, not slugs.** The archive URL is
  derived from the name the way WordPress derived it, so `Winner's Story`
  becomes `/blog/category/winners-story/`. Reuse an existing name to file a post
  under an existing term; a new name creates a new archive page.
- **`body_html` is rendered as-is.** It is not escaped, so treat these files as
  trusted content — the same trust level as a template. Do not paste in markup
  from an untrusted source.
- **Images go in `static/blog/uploads/`** and are referenced as
  `/blog/wp-content/uploads/<year>/<month>/<file>`. The odd path is worth
  keeping: it is where the existing images already are and where Google Images
  has them indexed.
- **`published` drives ordering** on the index and the `lastmod` in the sitemap.
  ISO 8601 with a timezone.

A new post joins `/blog/`, its category and tag archives, the RSS feed and
`sitemap.xml` automatically. Nothing else needs touching.

## Re-running the recovery

`tools/blog_harvest.py` is build-time only. It needs `beautifulsoup4`, `lxml`
and `Pillow` (see `requirements-dev.txt`), which the running site does not.

```bash
python tools/blog_harvest.py --posts     # rewrite content/blog from the archive
python tools/blog_harvest.py --images    # fetch and recompress static/blog/uploads
python tools/blog_harvest.py --relink    # re-apply link rewriting to what is on disk
```

Existing files are skipped unless `--force` is passed, so an interrupted run
resumes. `--relink` is the one to use after changing `LEGACY_LINKS`: it fixes the
links in the stored bodies without refetching 115 pages.

What the harvest does to a post on the way in, and why:

- Takes the **newest** capture that returned 200, so posts are at their last
  published state.
- Strips the old marketing stack — HubSpot CTAs, MonsterInsights, Google Tag
  Manager, all `<script>` — and keeps YouTube and Vimeo embeds.
- Rewrites images away from the ShortPixel proxy back to local paths, and drops
  the lazy-load placeholders.
- Rewrites in-body links to canonical URLs: `/lotteries/Irish-Lotto/Lucky-5`
  becomes `/play/lotto-ie`, retired products point at `/catalog`, and campaign
  tags on internal links are dropped. Those internal links are part of why the
  product pages rank, so they should land in one hop.
- Repairs the stray Windows-1252 bytes in otherwise-UTF-8 pages.

## What did not come back

- **Comments.** They were not captured and are not returning; `/blog/comments/feed/`
  answers 410.
- **Exact final revisions** for a handful of posts, where the newest capture
  predates the last edit.
- **Four posts have no meta description**, so the page falls back to the opening
  of the article. Worth writing by hand if those posts matter.
- **The WordPress admin.** Publishing is now the files above.
