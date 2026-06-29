# Bash completion for subtract_xsf.py and subtract_xsf_values.py.
#
# Enable it for the current shell with:
#   source subtract_xsf_completion.bash
#
# To enable it permanently, add that command (using the full path) to ~/.bashrc.

# This creates short commands that work from any directory.
_SUBTRACT_XSF_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
_SUBTRACT_XSF_SCRIPT="${_SUBTRACT_XSF_DIR}/subtract_xsf.py"
_SUBTRACT_XSF_VALUES_SCRIPT="${_SUBTRACT_XSF_DIR}/subtract_xsf_values.py"

subtract_xsf()
{
    command "$_SUBTRACT_XSF_SCRIPT" "$@"
}

subtract_xsf_values()
{
    command "$_SUBTRACT_XSF_VALUES_SCRIPT" "$@"
}

_subtract_xsf_complete()
{
    local current previous
    current=${COMP_WORDS[COMP_CWORD]}
    previous=${COMP_WORDS[COMP_CWORD-1]}

    case "$previous" in
        -o|--output)
            COMPREPLY=($(compgen -f -- "$current"))
            return
            ;;
        --offset-a|--offset-b)
            # Offsets are arbitrary numbers, so there is no finite value list.
            COMPREPLY=()
            return
            ;;
    esac

    if [[ "$current" == -* ]]; then
        local options
        options="
            --help
            --offset-a
            --offset-b
            --align-minima
            --force
        "
        COMPREPLY=($(compgen -W "$options" -- "$current"))
    else
        COMPREPLY=($(compgen -f -X '!*.xsf' -- "$current"))
    fi
}

# Completion used when the script is launched as:
#   python3 subtract_xsf.py ...
_subtract_xsf_python_complete()
{
    local script
    script=${COMP_WORDS[1]##*/}

    if [[ "$script" == "subtract_xsf.py" || "$script" == "subtract_xsf_values.py" ]]; then
        _subtract_xsf_complete
    else
        # Keep ordinary filename completion for other Python commands.
        COMPREPLY=($(compgen -f -- "${COMP_WORDS[COMP_CWORD]}"))
    fi
}

complete -F _subtract_xsf_complete subtract_xsf.py
complete -F _subtract_xsf_complete ./subtract_xsf.py
complete -F _subtract_xsf_complete subtract_xsf
complete -F _subtract_xsf_complete subtract_xsf_values.py
complete -F _subtract_xsf_complete ./subtract_xsf_values.py
complete -F _subtract_xsf_complete subtract_xsf_values
complete -F _subtract_xsf_python_complete python3
complete -F _subtract_xsf_python_complete python
