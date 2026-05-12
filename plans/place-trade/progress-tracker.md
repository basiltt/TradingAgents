# Place Trade Feature — Progress Tracker

## Phase 1: Backend
- [ ] Add `place_market_order` and `set_leverage` to `BybitClient`
- [ ] Add `PlaceTradeRequest` schema
- [ ] Add `POST /accounts/{id}/trade` endpoint
- [ ] Add `place_trade` method to `AccountsService`

## Phase 2: Frontend
- [ ] Add `PlaceTradeDialog` component
- [ ] Add `placeTrade` API method to client
- [ ] Add "Trade" button to `ResultsTable` in `ScanDetailPage`
- [ ] Wire up the dialog with account selection, direction, leverage, TP%, SL%

## Phase 3: Testing & Validation
- [ ] Manual test with dev server
- [ ] Verify error handling
