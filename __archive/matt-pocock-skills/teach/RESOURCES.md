# The Language of Building KDPS — Resources

Trusted sources for the business and technical vocabulary behind KDPS. Definitions in lessons should trace back to these, not to guesswork.

## Knowledge

### Business / retail terms
- [Wikipedia: Sale or return](https://en.wikipedia.org/wiki/Sale_or_return)
  Clear, neutral definition of the consignment-style model. Use for: SOR ownership, return windows.
- [Investopedia: Consignment](https://www.investopedia.com/terms/c/consignment.asp) · [Gross Margin](https://www.investopedia.com/terms/g/grossmargin.asp)
  Plain-English finance definitions. Use for: SOR vs outright, margin vs commission, markdown.
- [Wikipedia: Maximum retail price (MRP)](https://en.wikipedia.org/wiki/Maximum_retail_price)
  India-specific legal price cap. Use for: MRP, why KDPS can't price above the tag.
- [CBIC — GST (Government of India)](https://www.cbic-gst.gov.in/)
  Official source. Use for: GST, GSTIN, HSN codes, tax breakup.

### Technical / architecture terms
- [MDN: Client-Server overview](https://developer.mozilla.org/en-US/docs/Learn/Server-side/First_steps/Client-Server_overview)
  Plain, trusted explainer of how a browser, server and database talk. Use for: the four-box model (screen / brain / memory / outside world), the request→response journey.
- [Git — official book (Pro Git), ch. 1–2](https://git-scm.com/book/en/v2)
  The authoritative, free Git book. Use for: Lesson 3 — Git as the undo button, commits, branches, recovery.
- [Martin Fowler: Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html)
  The canonical write-up of the ledger / append-only idea. Use for: stock ledger, immutability, replay.
- [PostgreSQL Documentation](https://www.postgresql.org/docs/current/tutorial-transactions.html)
  Authoritative. Use for: transactions, ACID, why the database can't end up half-saved.
- [web.dev: Progressive Web Apps (Google)](https://web.dev/explore/progressive-web-apps)
  Use for: PWA, camera/barcode on cheap phones, no app-store install.
- [ERPNext](https://erpnext.com/) · [Frappe docs](https://docs.frappe.io/)
  The proposed spine platform. Use for: stock ledger entry, item variants (size×color), GRN, GST.

## Wisdom (Communities)
- [Frappe / ERPNext Forum](https://discuss.frappe.io/)
  High-signal, India-heavy, lots of multi-store retail setups. Use for: testing spine design ideas against people who run ERPNext at scale.
- [r/ExperiencedDevs](https://www.reddit.com/r/ExperiencedDevs/) / [Software Engineering Stack Exchange](https://softwareengineering.stackexchange.com/)
  Use for: sanity-checking architecture decisions (spine vs edge, where AI belongs).

> Note: Anand hasn't been asked about communities yet. Surface one only when a question clearly needs real-world practitioner wisdom.

## Gaps
- No single source yet for *fashion-retail-specific* software patterns (size curves, SOR deadline tracking). May need to assemble from practitioner blogs later.
