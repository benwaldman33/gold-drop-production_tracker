import { normalizeText } from "./domain.js";

export function createSeedState() {
  const now = new Date().toISOString();
  return {
    session: null,
    suppliers: [
      {
        id: "sup-001",
        name: "Farmlane",
        contact_name: "Maya Ortiz",
        phone: "555-0111",
        email: "sales@farmlane.example",
        location: "Salinas, CA",
        notes: "Regular biomass seller",
      },
      {
        id: "sup-002",
        name: "Cedar Ridge Cultivation",
        contact_name: "Jordan Lee",
        phone: "555-0122",
        email: "buying@cedarridge.example",
        location: "Monterey, CA",
        notes: "Needs follow-up on packaging",
      },
      {
        id: "sup-003",
        name: "Blue Coast Farms",
        contact_name: "Eli Grant",
        phone: "555-0144",
        email: "orders@bluecoast.example",
        location: "Paso Robles, CA",
        notes: "High potency lots",
      },
    ],
    opportunities: [
      {
        id: "opp-1001",
        status: "submitted",
        editable: true,
        delivery_allowed: false,
        supplier: { id: "sup-001", name: "Farmlane" },
        strain_name: "Blue Dream",
        expected_weight_lbs: 350,
        expected_potency_pct: 23.5,
        offered_price_per_lb: 285,
        availability_date: "2026-04-18",
        clean_or_dirty: "clean",
        testing_notes: "fresh lot, confirm moisture",
        notes: "Field note captured from buyer call",
        approval: null,
        delivery: null,
        photos: [],
        submitted_at: now,
        updated_at: now,
        delivery_needed: false,
      },
      {
        id: "opp-1002",
        status: "approved",
        editable: false,
        delivery_allowed: true,
        supplier: { id: "sup-002", name: "Cedar Ridge Cultivation" },
        strain_name: "Sour Diesel",
        expected_weight_lbs: 210,
        expected_potency_pct: 21.2,
        offered_price_per_lb: 270,
        availability_date: "2026-04-16",
        clean_or_dirty: "clean",
        testing_notes: "COA requested",
        notes: "Approved and ready for delivery",
        approval: {
          approved_at: "2026-04-12T18:20:00.000Z",
          approved_by_name: "Admin User",
        },
        delivery: null,
        photos: [],
        submitted_at: "2026-04-11T18:20:00.000Z",
        updated_at: "2026-04-12T18:20:00.000Z",
        delivery_needed: true,
      },
      {
        id: "opp-1003",
        status: "delivered",
        editable: false,
        delivery_allowed: false,
        supplier: { id: "sup-003", name: "Blue Coast Farms" },
        strain_name: "GMO",
        expected_weight_lbs: 180,
        expected_potency_pct: 25.1,
        offered_price_per_lb: 315,
        availability_date: "2026-04-08",
        clean_or_dirty: "clean",
        testing_notes: "delivery completed",
        notes: "Delivered with photos",
        approval: {
          approved_at: "2026-04-07T14:00:00.000Z",
          approved_by_name: "Buyer Lead",
        },
        delivery: {
          delivered_weight_lbs: 178.4,
          delivery_date: "2026-04-09",
          testing_status: "completed",
          actual_potency_pct: 25.0,
          clean_or_dirty: "clean",
          delivery_notes: "No issues on intake",
          delivered_by_name: "Buyer One",
        },
        photos: [
          {
            id: "ph-1001",
            url: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPSczMjAnIGhlaWdodD0nMzIwJz48cmVjdCB3aWR0aD0nMzIwJyBoZWlnaHQ9JzMyMCcgZmlsbD0nI2RlZmFnZScvPjx0ZXh0IHg9JzUwJScgeT0nNDglJyBmb250LXNpemU9JzI0JyBmaWxsPScjMWMxYzEnIHRleHQtYW5jaG9yPSdtaWRkbGUnPkNob3BlZCBiaW08L3RleHQ+PHRleHQgeD0nNTAlJyB5PSc1OCUnIGZvbnQtc2l6ZT0nMTgnIGZpbGw9JyMxYzFjMScgdGV4dC1hbmNob3I9J21pZGRsZSc+U291cmNlOiBCbHVlIENvYXN0PC90ZXh0Pjwvc3ZnPg==",
            photo_context: "delivery",
            name: "delivery-lineup.svg",
          },
        ],
        submitted_at: "2026-04-07T14:00:00.000Z",
        updated_at: "2026-04-09T13:10:00.000Z",
        delivery_needed: false,
      },
    ],
  };
}

export function cloneSeedState() {
  return JSON.parse(JSON.stringify(createSeedState()));
}

export function summarizeMockState(state) {
  const opportunities = state.opportunities || [];
  return {
    pending: opportunities.filter((opp) => normalizeText(opp.status) === "submitted").length,
    approved: opportunities.filter((opp) => normalizeText(opp.status) === "approved").length,
    committed: opportunities.filter((opp) => normalizeText(opp.status) === "committed").length,
    delivered: opportunities.filter((opp) => normalizeText(opp.status) === "delivered").length,
  };
}
