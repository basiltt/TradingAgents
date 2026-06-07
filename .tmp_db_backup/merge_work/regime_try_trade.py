    async def _try_trade(self, state: "_AccountState", result: Dict[str, Any], *, relaxed: bool = False, phase: str = "batch") -> Optional[TradeExecution]:
        cfg = state.config
        account_id = cfg.get("account_id", "")
        if result.get("status") != "completed":
            return None
        direction = result.get("direction", "hold")
        confidence = result.get("confidence", "none")
        score = abs(result.get("score", 0))
        ticker = result.get("ticker", "")
        if not ticker:
            return None
        symbol = f"{ticker}USDT" if not ticker.endswith("USDT") else ticker

        # ── Regime Multi-Strategy gates (all no-ops when no feature is enabled) ──
        ctx = self._scan_context
        # cohort is normally resolved to a concrete value in start_scan; coerce a
        # missing/None (tri-state "inherit") to the safe default so routing is defined.
        cohort = cfg.get("strategy_cohort") or "trend"
        # C5: a single coherent "MR account" rule — cohort says mean_reversion AND the
        # strategy is actually enabled. This couples strategy_cohort and
        # mean_reversion_enabled so neither (a) a trend account with a stray
        # mean_reversion_enabled gets kill-gated/routed, nor (b) an mr-cohort with the
        # strategy disabled silently keeps trading MR.
        is_mr_account = cohort == "mean_reversion" and bool(cfg.get("mean_reversion_enabled"))
        regime_active = bool(cfg.get("regime_filter_enabled")) or is_mr_account
        mr_fade = False  # set True only on the F2 placement path (Phase 4)
        if regime_active:
            # (0) master kill-switch (only __all__ is knowable before routing)
            if ctx.is_killed("__all__"):
                self._emit_decision(account_id, phase, symbol, "skipped", ReasonCode.FEATURE_KILLED, result)
                state.trades_skipped += 1
                return None
            # (1b) per-feature kill: f2 for an MR account, else f1.
            feat = "f2" if is_mr_account else "f1"
            if ctx.is_killed(feat):
                self._emit_decision(account_id, phase, symbol, "skipped", ReasonCode.FEATURE_KILLED, result, feature=feat)
                state.trades_skipped += 1
                return None
            # (2) strategy routing — an MR account runs MR only in mr_regime, else skip;
            #     everything else runs trend. (F2 placement is wired in Phase 4.)
            if is_mr_account:
                regime = ctx.routing_regime(
                    cfg.get("btc_vol_interval", "1h"), cfg.get("btc_vol_lookback_candles", 14)
                )
                strategy = _router.route_strategy("mean_reversion", regime, mr_regime=cfg.get("mr_regime", "ranging"))
                if strategy == "none":
                    self._emit_decision(account_id, phase, symbol, "skipped", ReasonCode.MR_REGIME_EXCLUDED, result, regime=regime)
                    state.trades_skipped += 1
                    return None
                mr_fade = strategy == "mean_reversion"
            # (4) F1 market-condition gates (apply to BOTH strategies; subtractive)
            session_skip = _f1.gate_session(cfg, datetime.now(timezone.utc))
            if session_skip is not None:
                self._emit_decision(account_id, phase, symbol, "skipped", session_skip, result)
                state.trades_skipped += 1
                return None
            if _f1.btc_vol_unavailable(cfg, ctx):
                self._emit_decision(account_id, phase, symbol, "allowed_vol_unavailable", ReasonCode.VOL_UNAVAILABLE, result)
            vol_skip = _f1.gate_btc_vol(cfg, ctx)
            if vol_skip is not None:
                self._emit_decision(account_id, phase, symbol, "skipped", vol_skip, result)
                state.trades_skipped += 1
                return None

        blacklist = cfg.get("symbol_blacklist") or []
        if blacklist and symbol in blacklist:
            self._emit_decision(account_id, phase, symbol, "skipped", "blacklist", result)
            state.trades_skipped += 1
            return None
        whitelist = cfg.get("symbol_whitelist") or []
        if whitelist and symbol not in whitelist:
            self._emit_decision(account_id, phase, symbol, "skipped", "whitelist", result)
            state.trades_skipped += 1
            return None

        if symbol in state.existing_symbols:
            self._emit_decision(account_id, phase, symbol, "skipped", "already_held", result)
            state.trades_skipped += 1
            return None

        max_age = cfg.get("max_signal_age_minutes")
        if max_age and not relaxed and result.get("completed_at"):
            try:
                completed = datetime.fromisoformat(result["completed_at"].replace("Z", "+00:00"))
                age_minutes = (datetime.now(timezone.utc) - completed).total_seconds() / 60
                if age_minutes > max_age:
                    self._emit_decision(account_id, phase, symbol, "skipped", "max_signal_age", result, age=age_minutes, max=max_age)
                    state.trades_skipped += 1
                    return None
            except (ValueError, TypeError):
                pass

        if direction == "hold":
            self._emit_decision(account_id, phase, symbol, "skipped", "hold_signal", result)
            return None

        max_same_dir = cfg.get("max_same_direction")
        if max_same_dir and not mr_fade:
            # C3: this gate counts position_directions in SIGNAL space. MR places in
            # FADE space (side from price-vs-mean), so applying it to MR would count
            # the wrong axis. MR's own mr_max_trades cap governs concentration; skip
            # this trend-oriented gate for MR-routed candidates.
            is_reverse = cfg.get("direction") == "reverse"
            signal_dir = "short" if direction in ("short", "sell") else "long"
            actual_dir = ("long" if signal_dir == "short" else "short") if is_reverse else signal_dir
            same_dir_count = sum(1 for d in state.position_directions.values() if d == actual_dir)
            if same_dir_count >= max_same_dir:
                self._emit_decision(account_id, phase, symbol, "skipped", "max_same_direction", result)
                state.trades_skipped += 1
                return None

        # Sector concentration limit
        max_same_sector = cfg.get("max_same_sector")
        if max_same_sector:
            _get_sec = self._sector_service.get_sector if self._sector_service else _static_get_sector
            sector = _get_sec(symbol)
            if sector != "other":
                same_sector_count = sum(1 for s in state.existing_symbols if _get_sec(s) == sector)
                if same_sector_count >= max_same_sector:
                    self._emit_decision(account_id, phase, symbol, "skipped", "max_same_sector", result, sector=sector)
                    state.trades_skipped += 1
                    return None

        # Adaptive blacklist check (pre-computed by scanner_service).
        # FR-030: MR entries read the MR-scoped blacklist; trend entries read the
        # trend one. select_adaptive_blacklist is the single source of truth.
        adaptive_bl = _router.select_adaptive_blacklist(cfg, mr_fade=mr_fade)
        if adaptive_bl:
            bl_set = adaptive_bl if isinstance(adaptive_bl, set) else set(adaptive_bl)
            if symbol in bl_set:
                self._emit_decision(account_id, phase, symbol, "skipped", "adaptive_blacklist", result)
                state.trades_skipped += 1
                return None

        # Apply filters (skipped in relaxed/fill mode)
        signal_sides = cfg.get("signal_sides", "both")
        if signal_sides != "both" and not mr_fade:
            # C4: signal_sides filters the LLM signal direction, but MR places on the
            # FADE side (decoupled from the signal). Applying it to MR would block/admit
            # the wrong side. MR side is governed by mr_short_enabled/mr_long_enabled.
            _norm = {"long": "buy", "short": "sell", "Long": "buy", "Short": "sell"}
            normalized_side = _norm.get(signal_sides, signal_sides)
            normalized_dir = _norm.get(direction, direction)
            if normalized_side != normalized_dir:
                self._emit_decision(account_id, phase, symbol, "skipped", "signal_sides", result)
                return None

        if not relaxed:
            min_score = cfg.get("min_score", 0)
            if score < min_score:
                self._emit_decision(account_id, phase, symbol, "skipped", "min_score", result, score=score, min_score=min_score)
                state.trades_skipped += 1
                return None

            conf_filter = cfg.get("confidence_filter", "any")
            if conf_filter != "any":
                conf_order = {"high": 3, "moderate": 2, "low": 1, "none": 0}
                if conf_order.get(confidence, 0) < conf_order.get(conf_filter, 0):
                    self._emit_decision(account_id, phase, symbol, "skipped", "confidence_filter", result)
                    state.trades_skipped += 1
                    return None

        # Check limits
        if state.trades_executed >= cfg.get("max_trades", 999):
            self._emit_decision(account_id, phase, symbol, "skipped", "max_trades", result)
            state.stopped = True
            state.stopped_reason = "max_trades_reached"
            return None

        # Check target goal
        goal_type = cfg.get("target_goal_type")
        goal_value = cfg.get("target_goal_value")
        if goal_type and goal_value:
            if goal_type == "trade_count" and state.trades_executed >= goal_value:
                self._emit_decision(account_id, phase, symbol, "skipped", "target_goal_reached", result)
                state.stopped = True
                state.stopped_reason = "target_goal_reached"
                return None

        account_id = cfg["account_id"]

        if state.base_capital is None or state.base_capital <= 0:
            self._emit_decision(account_id, phase, symbol, "skipped", "no_balance", result)
            state.stopped = True
            state.stopped_reason = "no_balance_captured"
            return None

        # Price drift validation — skip if price already moved too far in signal
        # direction. SKIPPED for MR (mr_fade): the drift check is direction-aware on the
        # LLM signal direction, but an MR trade places on the FADE side (decoupled from
        # the signal), so checking drift against the signal axis would skip/admit the
        # wrong entries (SD12 — price_drift is trend-only). The MR geometry guards
        # (no-edge/fee-floor) already validate the MR entry against the mean.
        max_drift = cfg.get("max_price_drift_pct")
        analysis_price = result.get("analysis_price")
        if max_drift and analysis_price and not mr_fade:
            try:
                current_price = await self._accounts.get_mark_price(account_id, symbol)
                drift_pct = ((current_price - analysis_price) / analysis_price) * 100
                # Buy signal: skip if price already went UP (move consumed)
                # Sell signal: skip if price already went DOWN (move consumed)
                if direction in ("buy", "long") and drift_pct > max_drift:
                    self._emit_decision(account_id, phase, symbol, "skipped", "price_drift", result, drift=drift_pct)
                    state.trades_skipped += 1
                    return None
                if direction in ("sell", "short") and drift_pct < -max_drift:
                    self._emit_decision(account_id, phase, symbol, "skipped", "price_drift", result, drift=drift_pct)
                    state.trades_skipped += 1
                    return None
            except Exception:
                pass  # fail-open: proceed with trade if price check fails

        # ── F2 mean-reversion placement parameters (only when routed to MR) ──
        # Defaults = the trend path (unchanged when mr_fade is False => golden-safe).
        place_signal_direction = direction
        place_trade_direction = cfg.get("direction", "straight")
        place_leverage = cfg.get("leverage", 20)
        place_tp = cfg.get("take_profit_pct", 150)
        place_sl = cfg.get("stop_loss_pct", 100)
        place_capital = cfg.get("capital_pct", 5)
        strategy_kind = "trend"
        if mr_fade:
            mr = await self._compute_mr_params(state, cfg, result, symbol, direction, ctx, phase)
            if mr is None:
                return None  # an MR guard fired (already emitted) — skip
            place_signal_direction, place_trade_direction = mr["signal_direction"], "straight"
            place_leverage, place_tp, place_sl = mr["leverage"], mr["take_profit_pct"], mr["stop_loss_pct"]
            place_capital, strategy_kind = mr["capital_pct"], "mean_reversion"
            # FR-051: record a pre-submit intent so an orphaned MR position (order fills
            # but the trades-row write fails) can be reconciled to mean_reversion rather
            # than mislabeled trend. Keyed by (account, symbol, side) — the tuple the
            # reconciler matches on. Deleted after a successful create_trade below.
            _db = getattr(self._accounts, "_db", None)
            _mr_side = "Buy" if place_signal_direction == "long" else "Sell"
            try:
                from backend.services import pending_intents as _pi
                await _pi.write_intent(_db, account_id, symbol, _mr_side, "mean_reversion")
            except Exception:
                pass

        # Execute trade
        try:
            result_data = await asyncio.wait_for(
                self._accounts.place_trade(
                    account_id=account_id,
                    symbol=symbol,
                    signal_direction=place_signal_direction,
                    trade_direction=place_trade_direction,
                    leverage=place_leverage,
                    take_profit_pct=place_tp,
                    stop_loss_pct=place_sl,
                    capital_pct=place_capital,
                    base_capital=state.base_capital,
                    source="scanner",
                    scan_result_id=result.get("id"),
                    strategy_kind=strategy_kind,
                    strategy_cohort=cohort,
                    # FR-066/SD20: an entry is "f1-active" only when F1 could actually
                    # act on it — the umbrella flag AND at least one sub-gate enabled —
                    # and it was NOT placed under the one-time session-filter override.
                    # This keeps the before/after efficacy stats free of entries F1
                    # never touched (umbrella-on but both sub-gates off) or bypassed.
                    # FR-066/SD20: an entry is "f1-active" only when F1 could actually
                    # act on it (umbrella + a sub-gate) and was not placed under the
                    # one-time override. compute_f1_active is the single source of truth.
                    f1_active=_f1.compute_f1_active(cfg),
                ),
                timeout=30.0,
            )
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=result_data.get("side", direction),
                status="success",
                order_id=result_data.get("trade_id"),
                details=result_data,
            )
            state.trades_executed += 1
            state.executions.append(execution)
            state.existing_symbols.add(symbol)
            if mr_fade:
                # FR-051: trade row now exists -> remove the pre-submit intent. Shield
                # the delete so a cancellation HERE (e.g. scan cancel / wait_for timeout
                # at this await) can't skip it and leave a stale intent that would later
                # mislabel a different orphan on the same (account,symbol,side). The
                # trade row already exists, so the intent is no longer needed.
                try:
                    from backend.services import pending_intents as _pi
                    _db = getattr(self._accounts, "_db", None)
                    _mr_side = "Buy" if place_signal_direction == "long" else "Sell"
                    await asyncio.shield(_pi.delete_intent(_db, account_id, symbol, _mr_side))
                except Exception:
                    pass
            if mr_fade and self._close_svc and not state.mr_duration_rule_created:
                # FR-023: register the MR fast time-stop as a MAX_DURATION close rule
                # (minutes/60 = float hours, stored in close_rules.threshold_value NUMERIC
                # without truncation). This is the strategy-critical fast exit (data:
                # 1-3h holds win, 3-6h holds lose). The rule is account-level, which is
                # correct for an MR cohort: every position on the account is MR (the
                # `both` cohort was cut, so there's no trend position to clobber). Created
                # once per account per scan (flag-guarded), like the trend duration rule.
                from datetime import datetime as _dt, timezone as _tz
                try:
                    _mins = float(cfg.get("mr_time_stop_minutes", 120))
                    _rule = await self._close_svc.create_rule(
                        account_id=account_id,
                        rule_data={
                            "trigger_type": "MAX_DURATION",
                            "threshold_value": str(_mins / 60.0),
                            "reference_value": _dt.now(_tz.utc).isoformat(),
                        },
                    )
                    state.created_rule_ids.append(_rule.get("id"))
                    state.mr_duration_rule_created = True
                    logger.info("mr_time_stop_rule_created", extra={
                        "account_id": account_id, "minutes": _mins})
                except Exception as e:
                    logger.warning("mr_time_stop_rule_failed", extra={
                        "account_id": account_id, "error": str(e)[:200]})
            if self._recorder is not None and self._debug_ctx is not None:
                try:
                    self._recorder.emit_symbol_decision(
                        self._debug_ctx, account_id=account_id, phase=phase, symbol=symbol,
                        decision="placed", reason_code="placed_ok", reason_detail={},
                        scan_score=result.get("score"), scan_confidence=result.get("confidence"),
                        scan_direction=result.get("direction"), order_id=execution.order_id,
                    )
                except Exception:
                    pass
            if mr_fade:
                # IR4: MR side is the fade side (price-vs-mean), unrelated to the LLM
                # signal direction or the trend reverse knob. Record the real side.
                state.position_directions[symbol] = "long" if place_signal_direction == "long" else "short"
            else:
                _is_rev = cfg.get("direction") == "reverse"
                _sig_dir = "short" if direction in ("short", "sell") else "long"
                state.position_directions[symbol] = ("long" if _sig_dir == "short" else "short") if _is_rev else _sig_dir
            logger.info("auto_trade_executed", extra={
                "account_id": account_id, "symbol": symbol,
                "side": execution.side, "order_id": execution.order_id,
            })

            # Enable AI Manager for this account if configured.
            # FR-052: a mean-reversion placement must NOT auto-enable the AI manager
            # (MR positions are excluded from AI management — they have their own
            # fast/tight exits and the AI's logic would fight them).
            if (strategy_kind != "mean_reversion"
                    and cfg.get("ai_manager_enabled")
                    and account_id not in self._ai_manager_enabled_accounts):
                self._ai_manager_enabled_accounts.add(account_id)
                if self._ai_manager_service:
                    try:
                        # Preserve any existing config — only use defaults if no config exists yet
                        existing_config = None
                        try:
                            existing_dict = await self._ai_manager_service.get_config(account_id)
                            existing_config = _AIMConfig(**existing_dict)
                        except Exception:
                            pass
                        config_to_use = existing_config or _AIMConfig()
                        config_to_use.auto_enabled = True
                        await self._ai_manager_service.enable(account_id, config_to_use)
                        logger.info("ai_manager_auto_enabled", extra={"account_id": account_id})
                    except Exception as e:
                        logger.warning("ai_manager_auto_enable_failed", extra={
                            "account_id": account_id, "error": str(e)[:200],
                        })

            return execution

        except asyncio.TimeoutError:
            # Order may have been submitted to exchange before timeout.
            # Add to existing_symbols AND position_directions to prevent duplicate/excess trades.
            state.existing_symbols.add(symbol)
            if mr_fade:
                # IR4: record the real MR fade side, not the trend signal+reverse.
                state.position_directions[symbol] = "long" if place_signal_direction == "long" else "short"
            else:
                _is_rev = cfg.get("direction") == "reverse"
                _sig_dir = "short" if direction in ("short", "sell") else "long"
                state.position_directions[symbol] = ("long" if _sig_dir == "short" else "short") if _is_rev else _sig_dir
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=direction,
                status="failed",
                error="place_trade timeout (30s) — position may exist on exchange",
            )
            state.trades_failed += 1
            state.executions.append(execution)
            logger.error("auto_trade_timeout_phantom_risk", extra={
                "account_id": account_id, "symbol": symbol,
                "msg": "Trade may have opened on exchange without rules. Check positions.",
            })
            self._emit_decision(account_id, phase, symbol, "failed", "timeout", result)
            return execution

        except Exception as e:
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=direction,
                status="failed",
                error=str(e)[:512],
            )
            state.trades_failed += 1
            state.executions.append(execution)
            logger.warning("auto_trade_failed", extra={
                "account_id": account_id, "symbol": symbol, "error": str(e)[:512],
            })

            self._emit_decision(account_id, phase, symbol, "failed", "place_error", result, error=str(e)[:200])
            return execution


@dataclass
class _AccountState:
    config: Dict[str, Any]
    trades_executed: int = 0
    trades_failed: int = 0
    trades_skipped: int = 0
    base_capital: Optional[float] = None
    stopped: bool = False
    stopped_reason: Optional[str] = None
    rescued_by_recheck: bool = False
    close_rule_id: Optional[str] = None
    drawdown_rule_id: Optional[str] = None
    executions: List[TradeExecution] = field(default_factory=list)
    existing_symbols: set = field(default_factory=set)
    position_directions: Dict[str, str] = field(default_factory=dict)
    created_rule_ids: List[str] = field(default_factory=list)
    mr_duration_rule_created: bool = False  # FR-023: MR time-stop rule registered once/scan
