#!/bin/zsh
# F1.2 final battery: per-file runs (kill selections) + show-dump of
# EVERY survivor immediately (self-contained justification input).
MUT=/Users/sahajpatel/Code/cryto-bot-mut
PYBIN=/Users/sahajpatel/Code/cryto-bot/.venv/bin/python
export PYTHONPATH=$MUT/mutants/src
cd $MUT || exit 1
rm -rf mutants .mutmut-cache
mkdir -p mutants/src
cp -r src/cryptobot mutants/src/cryptobot
for f in risk/sizing.py risk/margin.py risk/rounding.py risk/policy.py execution/order_manager.py execution/fill_realism.py; do
  rm -f "mutants/src/cryptobot/$f"
done
for spec in \
  "sizing:src/cryptobot/risk/sizing.py:tests/acceptance/test_sizing_funding_clamp.py,tests/acceptance/test_risk_sizing.py,tests/unit/test_venue_rounding_v008.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py" \
  "margin:src/cryptobot/risk/margin.py:tests/unit/test_margin_sizing.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py" \
  "rounding:src/cryptobot/risk/rounding.py:tests/unit/test_risk_rounding.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py" \
  "fillrealism:src/cryptobot/execution/fill_realism.py:tests/unit/test_fill_realism.py,tests/unit/test_paper_fill_params.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py" \
  "policy:src/cryptobot/risk/policy.py:tests/acceptance/test_risk_gates.py,tests/acceptance/test_risk_v004.py,tests/acceptance/test_risk_v006.py,tests/acceptance/test_risk_v007.py,tests/acceptance/test_risk_v008.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py" \
  "ordermanager:src/cryptobot/execution/order_manager.py:tests/unit/test_execution_orders.py,tests/unit/test_execution_handoff.py,tests/unit/test_execution_e2e.py,tests/unit/test_mutation_kills.py,tests/unit/test_mutation_kills_round2.py"; do
  name="${spec%%:*}"; rest="${spec#*:}"; src="${rest%%:*}"; tests="${rest#*:}"
  rm -f "mutants/$src"
  python3 - "$src" "$tests" <<'EOF'
import re, sys
src, tests = sys.argv[1], sys.argv[2].split(",")
text = open("pyproject.toml").read()
text = re.sub(r"\n\[tool\.mutmut\].*?(?=\n\[|\Z)", "", text, flags=re.S)
tests_str = ", ".join(f'"{t}"' for t in tests)
text += f'\n[tool.mutmut]\nsource_paths = ["{src}"]\npytest_add_cli_args_test_selection = [{tests_str}]\n'
open("pyproject.toml", "w").write(text)
EOF
  nice $PYBIN -m mutmut run --max-children 4 > /dev/null 2>&1
  $PYBIN -m mutmut results > $MUT/final-$name.txt 2>&1
  $PYBIN -m mutmut results --all True 2>&1 | awk '{print $NF}' | sort | uniq -c > $MUT/final-$name-counts.txt
  : > $MUT/final-$name-show.txt
  grep -oE "cryptobot[^:]*" $MUT/final-$name.txt | while read -r mut; do
    echo "############ $mut" >> $MUT/final-$name-show.txt
    $PYBIN -m mutmut show "$mut" 2>&1 | grep -E "^[-+]" | grep -vE "^[-+]{3}" | head -n 8 >> $MUT/final-$name-show.txt
  done
  echo "$name done: $(cat $MUT/final-$name-counts.txt | tr '\n' ' ')"
done
echo FINAL-DONE
git checkout -- pyproject.toml
