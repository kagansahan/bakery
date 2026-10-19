ACTIVATE_SCRIPT="$CONDA_PREFIX/etc/conda/activate.d/cutlang_activate.sh"

if [ -f "$ACTIVATE_SCRIPT" ]; then
    sed -i '/^echo "For examples/d; /^echo "and for LHC/d; /^echo "https:\/\/github.com\/ADL4HEP/d' "$ACTIVATE_SCRIPT"
fi