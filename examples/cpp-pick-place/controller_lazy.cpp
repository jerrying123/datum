// Lazy mode: the same pick-and-place plan, but no generated artifacts are
// needed before the run. Parameter values are extracted from the parameter
// spec and saved SolidCraft files at startup through the shared evaluation
// core's C ABI, so this one executable cannot drift from the CAD directory it
// is pointed at. No compile-time constants are involved.
#include "plan.hpp"
#include "dparams_lazy.h"
#include <iostream>
#include <string>

namespace {
char error_text[1024];

struct LoadedArm { double upper_arm_length_m = 0, shoulder_height_m = 0, tool_length_m = 0; };

bool read_named(const char* name, double* out) {
    if (dparams_lazy_get(name, out) != 0) {
        dparams_lazy_error(error_text, sizeof error_text);
        std::cerr << "lazy read " << name << ": " << error_text << "\n";
        return false;
    }
    return true;
}

// Evaluates PROJECT/datum/spec.json for worktree main once and reads the arm
// dimensions. When evidence_path is given, the machine-readable lazy evidence
// record for this exact evaluation is written there before release.
bool load_arm(const char* project, LoadedArm& arm, bool need_shoulder, const char* evidence_path) {
    const std::string spec = std::string(project) + "/datum/spec.json";
    if (dparams_lazy_eval(project, spec.c_str(), "main") != 0) {
        dparams_lazy_error(error_text, sizeof error_text);
        std::cerr << "lazy evaluation failed for " << project << ": " << error_text << "\n";
        return false;
    }
    double forearm = 0, palm = 0, finger = 0;
    bool ok = read_named("upper_arm_length_m", &arm.upper_arm_length_m)
        && read_named("forearm_length_m", &forearm)
        && read_named("gripper_palm_length_m", &palm)
        && read_named("finger_length_m", &finger)
        && (!need_shoulder || read_named("shoulder_height_m", &arm.shoulder_height_m));
    arm.tool_length_m = forearm + palm + finger / 2;
    if (ok && evidence_path && dparams_lazy_evidence(evidence_path) != 0) {
        dparams_lazy_error(error_text, sizeof error_text);
        std::cerr << "lazy evidence write failed: " << error_text << "\n";
        ok = false;
    }
    dparams_lazy_release();
    return ok;
}
} // namespace

// Usage: pick_place_lazy CONTROLLER_PROJECT PHYSICAL_PROJECT pass|fail [EVIDENCE_PATH]
// CONTROLLER_PROJECT and PHYSICAL_PROJECT normally name the same reviewed CAD
// directory. Pointing them at different directories shows what running
// against a stale CAD snapshot looks like, while the executable itself never
// changes between the two runs.
int main(int argc, char** argv) {
    if (argc < 4 || argc > 5
        || (std::string(argv[3]) != "pass" && std::string(argv[3]) != "fail")) {
        std::cerr << "Usage: pick_place_lazy CONTROLLER_PROJECT PHYSICAL_PROJECT pass|fail [EVIDENCE_PATH]\n";
        return 2;
    }
    const double tolerance = 0.015; // illustrative position tolerance, metres
    LoadedArm controller_arm, physical_arm;
    if (!load_arm(argv[1], controller_arm, true, argc == 5 ? argv[4] : nullptr)) return 2;
    if (!load_arm(argv[2], physical_arm, false, nullptr)) return 2;
    const ArmPlan plan{controller_arm.upper_arm_length_m, controller_arm.shoulder_height_m,
                       controller_arm.tool_length_m};
    const int reached = run_plan(plan, physical_arm.tool_length_m, tolerance, std::cout);
    if (reached == 2) return 2;
    const bool passed = (std::string(argv[3]) == "pass");
    return (passed ? reached == 1 : reached == 0) ? 0 : 1;
}
