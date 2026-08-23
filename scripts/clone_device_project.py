#!/usr/bin/env python3
"""clone_device_project.py — the smallest Xcode project that can ship the clone.

    clone_device_project.py <project-dir> --name NAME --bundle-id ID --team TEAM

`device_render.sh` builds the reproduction with `swiftc` straight to a .app,
which is enough for a simulator and not enough for a phone: a device build has
to be signed, and signing needs a development provisioning profile for this
device. Only Xcode can mint one (`-allowProvisioningUpdates`), so putting the
clone on real hardware means giving it a project.

It uses a file-system synchronized group (objectVersion 77, Xcode 16+), so every
`.swift` and every resource dropped into the source folder is built without
touching this file again — which matters because the reproduction is regenerated
on every observe.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def uid(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24].upper()


def _pbx_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pbxproj(name: str, bundle_id: str, team: str, deployment_target: str,
            display_name: str = "") -> str:
    # The home-screen name is the original app's; the product, binary and
    # bundle id stay the clone's own so the two never collide on a device.
    display = (f"\n\t\t\t\tINFOPLIST_KEY_CFBundleDisplayName = {_pbx_string(display_name)};"
               if display_name else "")
    ids = {key: uid(f"{name}:{key}") for key in (
        "root", "mainGroup", "products", "target", "product", "syncGroup",
        "sources", "frameworks", "resources", "configList", "targetConfigList",
        "debug", "release", "targetDebug", "targetRelease")}
    common = f"""				CODE_SIGN_STYLE = Automatic;
				DEVELOPMENT_TEAM = {team};
				GENERATE_INFOPLIST_FILE = YES;{display}
				INFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIST_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait;
				IPHONEOS_DEPLOYMENT_TARGET = {deployment_target};
				PRODUCT_BUNDLE_IDENTIFIER = {bundle_id};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SDKROOT = iphoneos;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = 1;"""
    return f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 77;
	objects = {{

/* Begin PBXFileReference section */
		{ids['product']} /* {name}.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = {name}.app; sourceTree = BUILT_PRODUCTS_DIR; }};
/* End PBXFileReference section */

/* Begin PBXFileSystemSynchronizedRootGroup section */
		{ids['syncGroup']} /* {name} */ = {{isa = PBXFileSystemSynchronizedRootGroup; explicitFileTypes = {{}}; explicitFolders = (); path = {name}; sourceTree = "<group>"; }};
/* End PBXFileSystemSynchronizedRootGroup section */

/* Begin PBXFrameworksBuildPhase section */
		{ids['frameworks']} = {{
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXGroup section */
		{ids['mainGroup']} = {{
			isa = PBXGroup;
			children = (
				{ids['syncGroup']} /* {name} */,
				{ids['products']} /* Products */,
			);
			sourceTree = "<group>";
		}};
		{ids['products']} /* Products */ = {{
			isa = PBXGroup;
			children = (
				{ids['product']} /* {name}.app */,
			);
			name = Products;
			sourceTree = "<group>";
		}};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		{ids['target']} /* {name} */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {ids['targetConfigList']};
			buildPhases = (
				{ids['sources']},
				{ids['frameworks']},
				{ids['resources']},
			);
			buildRules = (
			);
			dependencies = (
			);
			fileSystemSynchronizedGroups = (
				{ids['syncGroup']} /* {name} */,
			);
			name = {name};
			productName = {name};
			productReference = {ids['product']} /* {name}.app */;
			productType = "com.apple.product-type.application";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		{ids['root']} = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1600;
				LastUpgradeCheck = 1600;
				TargetAttributes = {{
					{ids['target']} = {{
						CreatedOnToolsVersion = 16.0;
					}};
				}};
			}};
			buildConfigurationList = {ids['configList']};
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = {ids['mainGroup']};
			minimizedProjectReferenceProxies = 1;
			preferredProjectObjectVersion = 77;
			productRefGroup = {ids['products']} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{ids['target']} /* {name} */,
			);
		}};
/* End PBXProject section */

/* Begin PBXResourcesBuildPhase section */
		{ids['resources']} = {{
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXResourcesBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		{ids['sources']} = {{
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
		{ids['debug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_OBJC_ARC = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_TESTABILITY = YES;
				GCC_OPTIMIZATION_LEVEL = 0;
				ONLY_ACTIVE_ARCH = YES;
				SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;
				SWIFT_OPTIMIZATION_LEVEL = "-Onone";
			}};
			name = Debug;
		}};
		{ids['release']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_OBJC_ARC = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				SWIFT_COMPILATION_MODE = wholemodule;
			}};
			name = Release;
		}};
		{ids['targetDebug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{common}
			}};
			name = Debug;
		}};
		{ids['targetRelease']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{common}
			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		{ids['configList']} = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{ids['debug']} /* Debug */,
				{ids['release']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Debug;
		}};
		{ids['targetConfigList']} = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{ids['targetDebug']} /* Debug */,
				{ids['targetRelease']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Debug;
		}};
/* End XCConfigurationList section */
	}};
	rootObject = {ids['root']};
}}
"""


def scheme(name: str, target_id: str) -> str:
    reference = (f'<BuildableReference BuildableIdentifier="primary" '
                 f'BlueprintIdentifier="{target_id}" BuildableName="{name}.app" '
                 f'BlueprintName="{name}" ReferencedContainer="container:{name}.xcodeproj"/>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.7">
   <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
            {reference}
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         {reference}
      </BuildableProductRunnable>
   </LaunchAction>
</Scheme>
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--name", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--deployment-target", default="17.0")
    parser.add_argument("--display-name", default="",
                        help="CFBundleDisplayName — the original app's name")
    args = parser.parse_args(argv[1:])

    root = Path(args.project_dir)
    xcodeproj = root / f"{args.name}.xcodeproj"
    xcodeproj.mkdir(parents=True, exist_ok=True)
    (root / args.name).mkdir(parents=True, exist_ok=True)
    # A shared scheme, because `xcodebuild -derivedDataPath` refuses to work
    # with `-target` alone: "-scheme ... is required when specifying
    # -derivedDataPath".
    schemes = xcodeproj / "xcshareddata" / "xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    (schemes / f"{args.name}.xcscheme").write_text(
        scheme(args.name, uid(f"{args.name}:target")), encoding="utf-8")
    (xcodeproj / "project.pbxproj").write_text(
        pbxproj(args.name, args.bundle_id, args.team, args.deployment_target,
                args.display_name),
        encoding="utf-8")
    print(f"OK: wrote {xcodeproj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
