# Manager finding reproductions (01487ac + 352657d, 12 Oct ~19:15 IST)

Independent of (and prior to) Worker 5's audit probes.

1. FUTURE-VWAP QUOTE — REPRODUCED (executed). Two XRP trades (50ms@100,
   950ms@200) -> modeled quote at 100ms with mid 150.0. Only 100 was known
   at 100ms. Owner: W1 Q-008.
2. MARK CLOSE-AT-OPEN — REPRODUCED (code). prepare_benchmark_30d._convert_marks
   pairs open_time with close. Owner: W2 E-009 (version + rebuild derived).
3. CROSS-SYMBOL DEDUP — REPRODUCED (code). backtest.py:295 fingerprint joins
   channel|ts|payload with no symbol. Owner: W1 Q-008.
4. GAP-BAR QUALITY — REPRODUCED (code). 1->3 ID jump sets gap_before=True but
   to_s1_bar returns a normal bar; Session builds MarketView CLEAN. Owner:
   manager + W1 (bars/views/admission quality propagation).
5. WS STRANDING — REPRODUCED (structure). bridge.py reads only select()-ready
   sockets; ws.py accumulates complete frames in _buf (line 85, 146-157), so a
   coalesced second frame waits for the next kernel-readable event. Owner:
   W2 E-009.

BONUS (manager probe, NOT a defect): buy fills at the contemporaneous ask
(60001), ignoring a favorable trade print (59999.5). Nautilus matches on
quotes; precedence is correct. Regression test to be added at integration.
