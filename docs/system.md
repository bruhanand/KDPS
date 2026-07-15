# KDPS working:

Let's go from the start, taking different things into account, and let's discuss the whole KDPS working.  
The business runs on two seasons:

- Autumn/Winter (AW)
- Spring/Summer (SS)

Commercial models (defaults per booking)

Stored as two axes (ownership × return-terms + a rolling-top-up flag); the friendly label is derived:

- Buy & Sell (Outright) — KDPS owns; no returns. (Sub-types: with vendor barcode = MRP capped, or without = KDPS sets MRP.)
- 25-18-10 (Correction) — KDPS owns, but a capped return allowance: 25% full-price margin / 18% EOSS / 10% goods-return, on delivered goods (stretchable to 12–15%).
- SOR — brand owns; all unsold returns, no cap; fresh booking to reorder.
- Consignment — same as SOR but brand keeps topping up (no fresh booking); vendor collects the unsold.

## BOOKING:

The order is placed in advance of the season.
Rules:
Vendor (the legal entity, many brands under it) →
Brand (commercial model + return terms live here, brand by brand) →
Booking (one vendor + one brand + one season; never mixes brands).
Types:

- branded
- non-branded.

FYI:
What is considered brand?
Let us first understand what is a brand. A brand means that, at booking, you get a proper receiving. When stock comes to KDPS, it comes with an invoice, and the stock PT file is provided by the brand or the supplier.

Brand = booking receipt + stock + invoice + PT file + tagged goods.

When creating the booking in the system: (Software Process)

1. season is picked first — the handler selects the season (or generates the next one from the fixed pattern if it doesn't exist yet),
2. then the vendor/brand,
3. then uploads the receipt.

Tag:
Between booking and the season for which it is booked, the booking stays live and tracked:

1. When it is booked: Tag: BOOKED
2. Reached KDPS (Received quantity == booking quantity), then Tag: RECIEVED
3. Reached KDPS (Received quantity < booking quantity), Tag: PARTIALLY RECIEVED.

Booking structure:

- Whatever information is in the booking receipt or the booking DATA.
- Booking Lines (DATA) = per style-code → per size: quantity. Optional price/MRP (not mandatory).
- No colour at booking.
- Quantity-led, one optional estimated order value if the pricing is mentioned.
- Commercial model + snapshot of its terms ride on the booking (defaulted from the brand, overridable per booking).
- Auto booking number (e.g. BK-SS26-0012) will be generated for KDPS system, and if there is a booking number from the brand/vendor, that also stays in the system.
- Season picked from a system-derived list, never free text.

### For non-branded:

- Discussion deferred for later on.
- This is the most unorganized.
- It's done from anywhere: on call, on message, in person or through agents.
- Receipt for the booking is not standard, and sometimes they don't even provide it.
- For non-branded booking, an AGENT (per City for Suppliers) is involved, who takes care of the whole process till the item is received at KDPS. Agents are accountable until the goods are delivered and verified.
- Item is booked for the warehouse (items arrive at KDPS's warehouse in Ranchi).
- At inbound stock can be received in the system without booking information.
- Parked for v2

### For branded:

- Booking receipt from the brand is a source of data.
- Booked mostly for the store and also for warehouse.
- Data is mostly organized.
- Booking is taken care of until it is received at KDPS and verified by the supplier or an agent.
- Included in version 1

- User story for system:

1. Season is selected.
2. The receipt soft copy(PDF/Image) is uploaded.
3. Uploaded data is converted by AI agent into the data that feeds into the kdps system, and
4. a tag(mentioned above) is also made for the booking
