# nix/packages.nix — Jue Agent package built with uv2nix
{ inputs, ... }:
{
  perSystem =
    { pkgs, inputs', ... }:
    let
      jueVenv = pkgs.callPackage ./python.nix {
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
      };

      jueNpmLib = pkgs.callPackage ./lib.nix {
        npm-lockfile-fix = inputs'.npm-lockfile-fix.packages.default;
      };

      jueTui = pkgs.callPackage ./tui.nix {
        inherit jueNpmLib;
      };

      # Import bundled skills, excluding runtime caches
      bundledSkills = pkgs.lib.cleanSourceWith {
        src = ../skills;
        filter = path: _type: !(pkgs.lib.hasInfix "/index-cache/" path);
      };

      jueWeb = pkgs.callPackage ./web.nix {
        inherit jueNpmLib;
      };

      runtimeDeps = with pkgs; [
        nodejs_22
        ripgrep
        git
        openssh
        ffmpeg
        tirith
      ];

      runtimePath = pkgs.lib.makeBinPath runtimeDeps;

      # Lockfile hashes for dev shell stamps
      pyprojectHash = builtins.hashString "sha256" (builtins.readFile ../pyproject.toml);
      uvLockHash =
        if builtins.pathExists ../uv.lock then
          builtins.hashString "sha256" (builtins.readFile ../uv.lock)
        else
          "none";
    in
    {
      packages = {
        default = pkgs.stdenv.mkDerivation {
          pname = "jue-agent";
          version = (fromTOML (builtins.readFile ../pyproject.toml)).project.version;

          dontUnpack = true;
          dontBuild = true;
          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/jue-agent $out/bin
            cp -r ${bundledSkills} $out/share/jue-agent/skills
            cp -r ${jueWeb} $out/share/jue-agent/web_dist

            # copy pre-built TUI (same layout as dev: ui-tui/dist/ + node_modules/)
            mkdir -p $out/ui-tui
            cp -r ${jueTui}/lib/jue-tui/* $out/ui-tui/

            ${pkgs.lib.concatMapStringsSep "\n"
              (name: ''
                makeWrapper ${jueVenv}/bin/${name} $out/bin/${name} \
                  --suffix PATH : "${runtimePath}" \
                  --set JUE_BUNDLED_SKILLS $out/share/jue-agent/skills \
                  --set JUE_WEB_DIST $out/share/jue-agent/web_dist \
                  --set JUE_TUI_DIR $out/ui-tui \
                  --set JUE_PYTHON ${jueVenv}/bin/python3 \
                  --set JUE_NODE ${pkgs.nodejs_22}/bin/node
              '')
              [
                "jue"
                "jue-agent"
                "jue-acp"
              ]
            }

            runHook postInstall
          '';

          passthru.devShellHook = ''
            STAMP=".nix-stamps/jue-agent"
            STAMP_VALUE="${pyprojectHash}:${uvLockHash}"
            if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$STAMP_VALUE" ]; then
              echo "jue-agent: installing Python dependencies..."
              uv venv .venv --python ${pkgs.python312}/bin/python3 2>/dev/null || true
              source .venv/bin/activate
              uv pip install -e ".[all]"
              [ -d mini-swe-agent ] && uv pip install -e ./mini-swe-agent 2>/dev/null || true
              [ -d tinker-atropos ] && uv pip install -e ./tinker-atropos 2>/dev/null || true
              mkdir -p .nix-stamps
              echo "$STAMP_VALUE" > "$STAMP"
            else
              source .venv/bin/activate
              export JUE_PYTHON=${jueVenv}/bin/python3
            fi
          '';

          meta = with pkgs.lib; {
            description = "AI agent with advanced tool-calling capabilities";
            homepage = "https://github.com/miao339/jue-agent";
            mainProgram = "jue";
            license = licenses.mit;
            platforms = platforms.unix;
          };
        };

        tui = jueTui;
        web = jueWeb;

        fix-lockfiles = jueNpmLib.mkFixLockfiles {
          packages = [ jueTui jueWeb ];
        };
      };
    };
}
