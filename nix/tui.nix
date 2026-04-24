# nix/tui.nix — Jue TUI (Ink/React) compiled with tsc and bundled
{ pkgs, jueNpmLib, ... }:
let
  src = ../ui-tui;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-RU4qSHgJPMyfRSEJDzkG4+MReDZDc6QbTD2wisa5QE0=";
  };

  npm = jueNpmLib.mkNpmPassthru { folder = "ui-tui"; attr = "tui"; pname = "jue-tui"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "jue-tui";
  inherit src npmDeps version;

  doCheck = false;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/jue-tui

    cp -r dist $out/lib/jue-tui/dist

    # runtime node_modules
    cp -r node_modules $out/lib/jue-tui/node_modules

    # @jue/ink is a file: dependency, we need to copy it in fr
    rm -f $out/lib/jue-tui/node_modules/@jue/ink
    cp -r packages/jue-ink $out/lib/jue-tui/node_modules/@jue/ink

    # package.json needed for "type": "module" resolution
    cp package.json $out/lib/jue-tui/

    runHook postInstall
  '';
})
