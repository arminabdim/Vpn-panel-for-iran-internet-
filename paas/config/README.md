# config/

`entrypoint.sh` writes `config.json` here at start-up from the environment
variables — you do not need to edit anything by hand. If you want a fully
custom server (routing rules, several inbounds, REALITY, ...), drop your own
`config.json` in this folder and set the container command to:

    sing-box run -c /opt/openpath/config/config.json

(the entrypoint skips generation when that file already exists).
