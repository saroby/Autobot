#!/usr/bin/env python3
"""Generate a minimal but valid .xcodeproj/project.pbxproj for an iOS app.

Usage:
    python3 generate-pbxproj.py --name AppName --bundle-id com.saroby.appname \
        --deployment-target 26.0 --sources-dir AppName

Produces: AppName.xcodeproj/project.pbxproj

This is the fallback when xcodegen is not installed.
The generated project includes:
  - App target (iOS, SwiftUI)
  - Test target (Swift Testing)
  - Recursive source file discovery
  - Asset catalog reference
  - Auto code signing
"""

import argparse
import hashlib
import os
import sys

# ── UUID generation (deterministic from seed string) ──

def make_uuid(seed: str) -> str:
    """Generate a 24-char hex UUID deterministically from a seed string."""
    return hashlib.md5(seed.encode()).hexdigest()[:24].upper()


# ── Discover Swift source files recursively ──

def find_swift_files(base_dir: str) -> list[str]:
    """Find all .swift files relative to base_dir."""
    result = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".swift"):
                rel = os.path.relpath(os.path.join(root, f), base_dir)
                result.append(rel)
    result.sort()
    return result


def find_asset_catalogs(base_dir: str) -> list[str]:
    """Find .xcassets directories relative to base_dir."""
    result = []
    for root, dirs, _ in os.walk(base_dir):
        for d in dirs:
            if d.endswith(".xcassets"):
                rel = os.path.relpath(os.path.join(root, d), base_dir)
                result.append(rel)
    result.sort()
    return result


# ── pbxproj generation ──

def generate_pbxproj(
    app_name: str,
    bundle_id: str,
    deployment_target: str,
    sources_dir: str,
    tests_dir: str,
    team_id: str = "",
) -> str:
    """Generate a complete project.pbxproj content string."""

    # Collect source files
    app_swift_files = find_swift_files(sources_dir) if os.path.isdir(sources_dir) else []
    test_swift_files = find_swift_files(tests_dir) if os.path.isdir(tests_dir) else []
    asset_catalogs = find_asset_catalogs(sources_dir) if os.path.isdir(sources_dir) else []

    # ── Generate stable UUIDs ──
    uid = lambda s: make_uuid(f"{app_name}:{s}")

    ROOT_OBJ          = uid("root")
    MAIN_GROUP         = uid("mainGroup")
    APP_GROUP          = uid("appGroup")
    TEST_GROUP         = uid("testGroup")
    PRODUCTS_GROUP     = uid("productsGroup")
    FRAMEWORKS_GROUP   = uid("frameworksGroup")

    APP_TARGET         = uid("appTarget")
    TEST_TARGET        = uid("testTarget")

    APP_PRODUCT        = uid("appProduct")
    TEST_PRODUCT       = uid("testProduct")

    APP_SOURCES_PHASE  = uid("appSourcesPhase")
    APP_RESOURCES_PHASE = uid("appResourcesPhase")
    APP_FRAMEWORKS_PHASE = uid("appFrameworksPhase")

    TEST_SOURCES_PHASE = uid("testSourcesPhase")
    TEST_FRAMEWORKS_PHASE = uid("testFrameworksPhase")

    DEBUG_CONFIG       = uid("debugConfig")
    RELEASE_CONFIG     = uid("releaseConfig")
    APP_DEBUG_CONFIG   = uid("appDebugConfig")
    APP_RELEASE_CONFIG = uid("appReleaseConfig")
    TEST_DEBUG_CONFIG  = uid("testDebugConfig")
    TEST_RELEASE_CONFIG = uid("testReleaseConfig")
    CONFIG_LIST        = uid("configList")
    APP_CONFIG_LIST    = uid("appConfigList")
    TEST_CONFIG_LIST   = uid("testConfigList")

    CONTAINER_PROXY    = uid("containerProxy")
    TARGET_DEPENDENCY  = uid("targetDependency")

    # ── File references & build files ──
    file_refs = []      # (uuid, path, name, sourceTree, lastKnownFileType)
    build_files = []    # (buildFileUuid, fileRefUuid, phase)
    app_group_children = []
    test_group_children = []

    for sf in app_swift_files:
        ref_id = uid(f"fileRef:{sf}")
        build_id = uid(f"buildFile:{sf}")
        name = os.path.basename(sf)
        file_refs.append((ref_id, sf, name, '"<group>"', "sourcecode.swift"))
        build_files.append((build_id, ref_id, "appSources"))
        app_group_children.append(ref_id)

    for ac in asset_catalogs:
        ref_id = uid(f"fileRef:{ac}")
        build_id = uid(f"buildFile:{ac}")
        name = os.path.basename(ac)
        file_refs.append((ref_id, ac, name, '"<group>"', "folder.assetcatalog"))
        build_files.append((build_id, ref_id, "appResources"))
        app_group_children.append(ref_id)

    for sf in test_swift_files:
        ref_id = uid(f"testFileRef:{sf}")
        build_id = uid(f"testBuildFile:{sf}")
        name = os.path.basename(sf)
        file_refs.append((ref_id, sf, name, '"<group>"', "sourcecode.swift"))
        build_files.append((build_id, ref_id, "testSources"))
        test_group_children.append(ref_id)

    # ── Build the pbxproj string ──
    lines = []
    w = lines.append

    w('// !$*UTF8*$!')
    w('{')
    w('\tarchiveVersion = 1;')
    w('\tclasses = {')
    w('\t};')
    w('\tobjectVersion = 56;')
    w('\tobjects = {')
    w('')

    # ── PBXBuildFile ──
    w('/* Begin PBXBuildFile section */')
    for bf_id, fr_id, _ in build_files:
        w(f'\t\t{bf_id} /* */ = {{isa = PBXBuildFile; fileRef = {fr_id}; }};')
    w('/* End PBXBuildFile section */')
    w('')

    # ── PBXContainerItemProxy ──
    w('/* Begin PBXContainerItemProxy section */')
    w(f'\t\t{CONTAINER_PROXY} = {{')
    w('\t\t\tisa = PBXContainerItemProxy;')
    w(f'\t\t\tcontainerPortal = {ROOT_OBJ};')
    w('\t\t\tproxyType = 1;')
    w(f'\t\t\tremoteGlobalIDString = {APP_TARGET};')
    w(f'\t\t\tremoteInfo = {app_name};')
    w('\t\t};')
    w('/* End PBXContainerItemProxy section */')
    w('')

    # ── PBXFileReference ──
    w('/* Begin PBXFileReference section */')
    w(f'\t\t{APP_PRODUCT} = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = "{app_name}.app"; sourceTree = BUILT_PRODUCTS_DIR; }};')
    w(f'\t\t{TEST_PRODUCT} = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = "{app_name}Tests.xctest"; sourceTree = BUILT_PRODUCTS_DIR; }};')
    for ref_id, path, name, tree, ftype in file_refs:
        w(f'\t\t{ref_id} = {{isa = PBXFileReference; lastKnownFileType = {ftype}; path = "{path}"; sourceTree = {tree}; }};')
    w('/* End PBXFileReference section */')
    w('')

    # ── PBXFrameworksBuildPhase ──
    w('/* Begin PBXFrameworksBuildPhase section */')
    w(f'\t\t{APP_FRAMEWORKS_PHASE} = {{')
    w('\t\t\tisa = PBXFrameworksBuildPhase;')
    w('\t\t\tbuildActionMask = 2147483647;')
    w('\t\t\tfiles = (')
    w('\t\t\t);')
    w('\t\t\trunOnlyForDeploymentPostprocessing = 0;')
    w('\t\t};')
    w(f'\t\t{TEST_FRAMEWORKS_PHASE} = {{')
    w('\t\t\tisa = PBXFrameworksBuildPhase;')
    w('\t\t\tbuildActionMask = 2147483647;')
    w('\t\t\tfiles = (')
    w('\t\t\t);')
    w('\t\t\trunOnlyForDeploymentPostprocessing = 0;')
    w('\t\t};')
    w('/* End PBXFrameworksBuildPhase section */')
    w('')

    # ── PBXGroup ──
    w('/* Begin PBXGroup section */')
    # Main group
    w(f'\t\t{MAIN_GROUP} = {{')
    w('\t\t\tisa = PBXGroup;')
    w('\t\t\tchildren = (')
    w(f'\t\t\t\t{APP_GROUP},')
    w(f'\t\t\t\t{TEST_GROUP},')
    w(f'\t\t\t\t{PRODUCTS_GROUP},')
    w('\t\t\t);')
    w('\t\t\tsourceTree = "<group>";')
    w('\t\t};')
    # App group
    w(f'\t\t{APP_GROUP} = {{')
    w('\t\t\tisa = PBXGroup;')
    w('\t\t\tchildren = (')
    for child in app_group_children:
        w(f'\t\t\t\t{child},')
    w('\t\t\t);')
    w(f'\t\t\tpath = "{app_name}";')
    w('\t\t\tsourceTree = "<group>";')
    w('\t\t};')
    # Test group
    w(f'\t\t{TEST_GROUP} = {{')
    w('\t\t\tisa = PBXGroup;')
    w('\t\t\tchildren = (')
    for child in test_group_children:
        w(f'\t\t\t\t{child},')
    w('\t\t\t);')
    w(f'\t\t\tpath = "{app_name}Tests";')
    w('\t\t\tsourceTree = "<group>";')
    w('\t\t};')
    # Products group
    w(f'\t\t{PRODUCTS_GROUP} = {{')
    w('\t\t\tisa = PBXGroup;')
    w('\t\t\tchildren = (')
    w(f'\t\t\t\t{APP_PRODUCT},')
    w(f'\t\t\t\t{TEST_PRODUCT},')
    w('\t\t\t);')
    w('\t\t\tname = Products;')
    w('\t\t\tsourceTree = "<group>";')
    w('\t\t};')
    w('/* End PBXGroup section */')
    w('')

    # ── PBXNativeTarget ──
    w('/* Begin PBXNativeTarget section */')
    # App target
    w(f'\t\t{APP_TARGET} = {{')
    w('\t\t\tisa = PBXNativeTarget;')
    w(f'\t\t\tbuildConfigurationList = {APP_CONFIG_LIST};')
    w('\t\t\tbuildPhases = (')
    w(f'\t\t\t\t{APP_SOURCES_PHASE},')
    w(f'\t\t\t\t{APP_FRAMEWORKS_PHASE},')
    w(f'\t\t\t\t{APP_RESOURCES_PHASE},')
    w('\t\t\t);')
    w('\t\t\tbuildRules = (')
    w('\t\t\t);')
    w('\t\t\tdependencies = (')
    w('\t\t\t);')
    w(f'\t\t\tname = "{app_name}";')
    w(f'\t\t\tproductName = "{app_name}";')
    w(f'\t\t\tproductReference = {APP_PRODUCT};')
    w('\t\t\tproductType = "com.apple.product-type.application";')
    w('\t\t};')
    # Test target
    w(f'\t\t{TEST_TARGET} = {{')
    w('\t\t\tisa = PBXNativeTarget;')
    w(f'\t\t\tbuildConfigurationList = {TEST_CONFIG_LIST};')
    w('\t\t\tbuildPhases = (')
    w(f'\t\t\t\t{TEST_SOURCES_PHASE},')
    w(f'\t\t\t\t{TEST_FRAMEWORKS_PHASE},')
    w('\t\t\t);')
    w('\t\t\tbuildRules = (')
    w('\t\t\t);')
    w('\t\t\tdependencies = (')
    w(f'\t\t\t\t{TARGET_DEPENDENCY},')
    w('\t\t\t);')
    w(f'\t\t\tname = "{app_name}Tests";')
    w(f'\t\t\tproductName = "{app_name}Tests";')
    w(f'\t\t\tproductReference = {TEST_PRODUCT};')
    w('\t\t\tproductType = "com.apple.product-type.bundle.unit-test";')
    w('\t\t};')
    w('/* End PBXNativeTarget section */')
    w('')

    # ── PBXProject ──
    w('/* Begin PBXProject section */')
    w(f'\t\t{ROOT_OBJ} = {{')
    w('\t\t\tisa = PBXProject;')
    w(f'\t\t\tbuildConfigurationList = {CONFIG_LIST};')
    w('\t\t\tcompatibilityVersion = "Xcode 14.0";')
    w('\t\t\tdevelopmentRegion = en;')
    w('\t\t\thasScannedForEncodings = 0;')
    w('\t\t\tknownRegions = (')
    w('\t\t\t\ten,')
    w('\t\t\t\tBase,')
    w('\t\t\t\tko,')
    w('\t\t\t);')
    w(f'\t\t\tmainGroup = {MAIN_GROUP};')
    w(f'\t\t\tproductRefGroup = {PRODUCTS_GROUP};')
    w('\t\t\tprojectDirPath = "";')
    w('\t\t\tprojectRoot = "";')
    w('\t\t\ttargets = (')
    w(f'\t\t\t\t{APP_TARGET},')
    w(f'\t\t\t\t{TEST_TARGET},')
    w('\t\t\t);')
    w('\t\t};')
    w('/* End PBXProject section */')
    w('')

    # ── PBXResourcesBuildPhase ──
    w('/* Begin PBXResourcesBuildPhase section */')
    w(f'\t\t{APP_RESOURCES_PHASE} = {{')
    w('\t\t\tisa = PBXResourcesBuildPhase;')
    w('\t\t\tbuildActionMask = 2147483647;')
    w('\t\t\tfiles = (')
    for bf_id, _, phase in build_files:
        if phase == "appResources":
            w(f'\t\t\t\t{bf_id},')
    w('\t\t\t);')
    w('\t\t\trunOnlyForDeploymentPostprocessing = 0;')
    w('\t\t};')
    w('/* End PBXResourcesBuildPhase section */')
    w('')

    # ── PBXSourcesBuildPhase ──
    w('/* Begin PBXSourcesBuildPhase section */')
    w(f'\t\t{APP_SOURCES_PHASE} = {{')
    w('\t\t\tisa = PBXSourcesBuildPhase;')
    w('\t\t\tbuildActionMask = 2147483647;')
    w('\t\t\tfiles = (')
    for bf_id, _, phase in build_files:
        if phase == "appSources":
            w(f'\t\t\t\t{bf_id},')
    w('\t\t\t);')
    w('\t\t\trunOnlyForDeploymentPostprocessing = 0;')
    w('\t\t};')
    w(f'\t\t{TEST_SOURCES_PHASE} = {{')
    w('\t\t\tisa = PBXSourcesBuildPhase;')
    w('\t\t\tbuildActionMask = 2147483647;')
    w('\t\t\tfiles = (')
    for bf_id, _, phase in build_files:
        if phase == "testSources":
            w(f'\t\t\t\t{bf_id},')
    w('\t\t\t);')
    w('\t\t\trunOnlyForDeploymentPostprocessing = 0;')
    w('\t\t};')
    w('/* End PBXSourcesBuildPhase section */')
    w('')

    # ── PBXTargetDependency ──
    w('/* Begin PBXTargetDependency section */')
    w(f'\t\t{TARGET_DEPENDENCY} = {{')
    w('\t\t\tisa = PBXTargetDependency;')
    w(f'\t\t\ttarget = {APP_TARGET};')
    w(f'\t\t\ttargetProxy = {CONTAINER_PROXY};')
    w('\t\t};')
    w('/* End PBXTargetDependency section */')
    w('')

    # ── XCBuildConfiguration ──
    team_setting = f'\t\t\t\tDEVELOPMENT_TEAM = "{team_id}";' if team_id else '\t\t\t\tDEVELOPMENT_TEAM = "";'

    w('/* Begin XCBuildConfiguration section */')
    # Project-level Debug
    w(f'\t\t{DEBUG_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w('\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;')
    w('\t\t\t\tCLANG_ENABLE_MODULES = YES;')
    w('\t\t\t\tCOPY_PHASE_STRIP = NO;')
    w('\t\t\t\tDEBUG_INFORMATION_FORMAT = dwarf;')
    w('\t\t\t\tENABLE_STRICT_OBJC_MSGSEND = YES;')
    w('\t\t\t\tENABLE_TESTABILITY = YES;')
    w('\t\t\t\tGCC_OPTIMIZATION_LEVEL = 0;')
    w(f'\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {deployment_target};')
    w('\t\t\t\tONLY_ACTIVE_ARCH = YES;')
    w('\t\t\t\tSDKROOT = iphoneos;')
    w('\t\t\t\tSWIFT_ACTIVE_COMPILATION_CONDITIONS = "$(inherited) DEBUG";')
    w('\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Onone";')
    w('\t\t\t\tSWIFT_STRICT_CONCURRENCY = complete;')
    w('\t\t\t\tSWIFT_VERSION = 6.0;')
    w('\t\t\t};')
    w('\t\t\tname = Debug;')
    w('\t\t};')
    # Project-level Release
    w(f'\t\t{RELEASE_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w('\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;')
    w('\t\t\t\tCLANG_ENABLE_MODULES = YES;')
    w('\t\t\t\tCOPY_PHASE_STRIP = NO;')
    w('\t\t\t\tDEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";')
    w('\t\t\t\tENABLE_NS_ASSERTIONS = NO;')
    w('\t\t\t\tENABLE_STRICT_OBJC_MSGSEND = YES;')
    w(f'\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {deployment_target};')
    w('\t\t\t\tSDKROOT = iphoneos;')
    w('\t\t\t\tSWIFT_COMPILATION_MODE = wholemodule;')
    w('\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-O";')
    w('\t\t\t\tSWIFT_STRICT_CONCURRENCY = complete;')
    w('\t\t\t\tSWIFT_VERSION = 6.0;')
    w('\t\t\t\tVALIDATE_PRODUCT = YES;')
    w('\t\t\t};')
    w('\t\t\tname = Release;')
    w('\t\t};')
    # App Debug
    w(f'\t\t{APP_DEBUG_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w(f'\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;')
    w(f'\t\t\t\tCODE_SIGN_STYLE = Automatic;')
    w(f'\t\t\t\tCURRENT_PROJECT_VERSION = 1;')
    w(f'{team_setting}')
    w(f'\t\t\t\tGENERATE_INFOPLIST_FILE = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPad = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";')
    w(f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";')
    w(f'\t\t\t\tMARKETING_VERSION = 1.0.0;')
    w(f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}";')
    w(f'\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";')
    w(f'\t\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;')
    w(f'\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";')
    w('\t\t\t};')
    w('\t\t\tname = Debug;')
    w('\t\t};')
    # App Release
    w(f'\t\t{APP_RELEASE_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w(f'\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;')
    w(f'\t\t\t\tCODE_SIGN_STYLE = Automatic;')
    w(f'\t\t\t\tCURRENT_PROJECT_VERSION = 1;')
    w(f'{team_setting}')
    w(f'\t\t\t\tGENERATE_INFOPLIST_FILE = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;')
    w(f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPad = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";')
    w(f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";')
    w(f'\t\t\t\tMARKETING_VERSION = 1.0.0;')
    w(f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}";')
    w(f'\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";')
    w(f'\t\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;')
    w(f'\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";')
    w('\t\t\t};')
    w('\t\t\tname = Release;')
    w('\t\t};')
    # Test Debug
    w(f'\t\t{TEST_DEBUG_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w(f'\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";')
    w(f'\t\t\t\tCODE_SIGN_STYLE = Automatic;')
    w(f'\t\t\t\tCURRENT_PROJECT_VERSION = 1;')
    w(f'{team_setting}')
    w(f'\t\t\t\tGENERATE_INFOPLIST_FILE = YES;')
    w(f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}.tests";')
    w(f'\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";')
    w(f'\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/{app_name}.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/{app_name}";')
    w('\t\t\t};')
    w('\t\t\tname = Debug;')
    w('\t\t};')
    # Test Release
    w(f'\t\t{TEST_RELEASE_CONFIG} = {{')
    w('\t\t\tisa = XCBuildConfiguration;')
    w('\t\t\tbuildSettings = {')
    w(f'\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";')
    w(f'\t\t\t\tCODE_SIGN_STYLE = Automatic;')
    w(f'\t\t\t\tCURRENT_PROJECT_VERSION = 1;')
    w(f'{team_setting}')
    w(f'\t\t\t\tGENERATE_INFOPLIST_FILE = YES;')
    w(f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "{bundle_id}.tests";')
    w(f'\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";')
    w(f'\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/{app_name}.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/{app_name}";')
    w('\t\t\t};')
    w('\t\t\tname = Release;')
    w('\t\t};')
    w('/* End XCBuildConfiguration section */')
    w('')

    # ── XCConfigurationList ──
    w('/* Begin XCConfigurationList section */')
    w(f'\t\t{CONFIG_LIST} = {{')
    w('\t\t\tisa = XCConfigurationList;')
    w('\t\t\tbuildConfigurations = (')
    w(f'\t\t\t\t{DEBUG_CONFIG},')
    w(f'\t\t\t\t{RELEASE_CONFIG},')
    w('\t\t\t);')
    w('\t\t\tdefaultConfigurationIsVisible = 0;')
    w('\t\t\tdefaultConfigurationName = Release;')
    w('\t\t};')
    w(f'\t\t{APP_CONFIG_LIST} = {{')
    w('\t\t\tisa = XCConfigurationList;')
    w('\t\t\tbuildConfigurations = (')
    w(f'\t\t\t\t{APP_DEBUG_CONFIG},')
    w(f'\t\t\t\t{APP_RELEASE_CONFIG},')
    w('\t\t\t);')
    w('\t\t\tdefaultConfigurationIsVisible = 0;')
    w('\t\t\tdefaultConfigurationName = Release;')
    w('\t\t};')
    w(f'\t\t{TEST_CONFIG_LIST} = {{')
    w('\t\t\tisa = XCConfigurationList;')
    w('\t\t\tbuildConfigurations = (')
    w(f'\t\t\t\t{TEST_DEBUG_CONFIG},')
    w(f'\t\t\t\t{TEST_RELEASE_CONFIG},')
    w('\t\t\t);')
    w('\t\t\tdefaultConfigurationIsVisible = 0;')
    w('\t\t\tdefaultConfigurationName = Release;')
    w('\t\t};')
    w('/* End XCConfigurationList section */')

    w('\t};')
    w(f'\trootObject = {ROOT_OBJ};')
    w('}')

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description="Generate Xcode project.pbxproj")
    parser.add_argument("--name", required=True, help="App name (PascalCase)")
    parser.add_argument("--bundle-id", required=True, help="Bundle identifier")
    parser.add_argument("--deployment-target", default="26.0", help="iOS deployment target")
    parser.add_argument("--sources-dir", required=True, help="Path to app source directory")
    parser.add_argument("--team-id", default="", help="Development team ID")
    args = parser.parse_args()

    app_name = args.name
    sources_dir = args.sources_dir
    tests_dir = os.path.join(os.path.dirname(sources_dir), f"{app_name}Tests")
    project_dir = os.path.dirname(sources_dir)
    xcodeproj_dir = os.path.join(project_dir, f"{app_name}.xcodeproj")

    # Generate
    pbxproj = generate_pbxproj(
        app_name=app_name,
        bundle_id=args.bundle_id,
        deployment_target=args.deployment_target,
        sources_dir=sources_dir,
        tests_dir=tests_dir,
        team_id=args.team_id,
    )

    # Write
    os.makedirs(xcodeproj_dir, exist_ok=True)
    pbxproj_path = os.path.join(xcodeproj_dir, "project.pbxproj")
    with open(pbxproj_path, "w") as f:
        f.write(pbxproj)

    # Also create xcscheme for the app
    schemes_dir = os.path.join(xcodeproj_dir, "xcshareddata", "xcschemes")
    os.makedirs(schemes_dir, exist_ok=True)

    scheme_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.7">
   <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
            <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{make_uuid(f'{app_name}:appTarget')}" BuildableName="{app_name}.app" BlueprintName="{app_name}" ReferencedContainer="container:{app_name}.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES">
      <Testables>
         <TestableReference skipped="NO">
            <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{make_uuid(f'{app_name}:testTarget')}" BuildableName="{app_name}Tests.xctest" BlueprintName="{app_name}Tests" ReferencedContainer="container:{app_name}.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{make_uuid(f'{app_name}:appTarget')}" BuildableName="{app_name}.app" BlueprintName="{app_name}" ReferencedContainer="container:{app_name}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES">
   </ArchiveAction>
</Scheme>"""

    with open(os.path.join(schemes_dir, f"{app_name}.xcscheme"), "w") as f:
        f.write(scheme_xml)

    print(f"Generated: {pbxproj_path}")
    print(f"Generated: {schemes_dir}/{app_name}.xcscheme")


if __name__ == "__main__":
    main()
