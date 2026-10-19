#!/bin/zsh
# F1.2 mutation battery (before AND after kill tests), serialized.
# Runs in the cryto-bot-mut scratch worktree. Results land beside it.
MUT=/Users/sahajpatel/Code/cryto-bot-mut
PYBIN=/Users/sahajpatel/Code/cryto-bot/.venv/bin/python
cd $MUT || exit 1

run_set() {
  tag="$1"; kills="$2"  # kills: "yes" includes test_mutation_kills.py
  for spec in \
    "sizing:src/cryptobot/risk/sizing.py:tests/acceptance/test_sizing_funding_clamp.py,tests/acceptance/test_risk_sizing.py,tests/unit/test_venue_rounding_v008.py" \
    "margin:src/cryptobot/risk/margin.py:tests/unit/test_margin_sizing.py" \
    "rounding:src/cryptobot/risk/rounding.py:tests/unit/test_risk_rounding.py" \
    "fillrealism:src/cryptobot/execution/fill_realism.py:tests/unit/test_fill_realism.py,tests/unit/test_paper_fill_params.py" \
    "policy:src/cryptobot/risk/policy.py:tests/acceptance/test_risk_gates.py,tests/acceptance/test_risk_v004.py,tests/acceptance/test_risk_v006.py,tests/acceptance/test_risk_v007.py,tests/acceptance/test_risk_v008.py" \
    "ordermanager:src/cryptobot/execution/order_manager.py:tests/unit/test_execution_orders.py,tests/unit/test_execution_handoff.py,tests/unit/test_execution_e2e.py"; do
    name="${spec%%:*}"; rest="${spec#*:}"; src="${rest%%:*}"; tests="${rest#*:}"
    if [ "$kills" = "yes" ]; then tests="$tests,tests/unit/test_mutation_kills.py"; fi
    rm -rf mutants .mutmut-cache; mkdir -p mutants/src
    cp -r src/cryptobot mutants/src/cryptobot; rm -f "mutants/$src"
    python3 - "$src" "$tests" <<'EOF'
import re, sys
src, tests = sys.argv[1], sys.argv[2].split(",")
text = open("pyproject.toml").read()
text = re.sub(r"\n\[tool\.mutmut\].*?(?=\n\[|\Z)", "", text, flags=re.S)
tests_str = ", ".join(f'"{t}"' for t in tests)
text += f'\n[tool.mutmut]\nsource_paths = ["{src}"]\npytest_add_cli_args_test_selection = [{tests_str}]\n'
open("pyproject.toml", "w").write(text)
EOF
    PYTHONPATH=$MUT/mutants/src nice $PYBIN -m mutmut run --max-children 4 > /dev/null 2>&1
    PYTHONPATH=$MUT/mutants/src $PYBIN -m mutmut results > $MUT/f1.2-$tag-$name.txt 2>&1
    PYTHONPATH=$MUT/mutants/src $PYBIN -m mutmut results --all True 2>&1 | awk '{print $NF}' | sort | uniq -c > $MUT/f1.2-$tag-$name-counts.txt
    echo "$tag/$name done: $(cat $MUT/f1.2-$tag-$name-counts.txt | tr '\n' ' ')"
  done
}

run_set before no
run_set after yes
echo BATTERY-DONE
git checkout -- pyproject.toml
