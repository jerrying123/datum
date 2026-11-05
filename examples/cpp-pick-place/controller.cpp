// Plan with one CAD-derived parameter set and evaluate against the changed arm.
#include "parameters.hpp"
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>

namespace p = datum::robot::main;
extern double physical_tool_length();

struct Target { const char* name; double x, z; };

int main(int argc, char** argv) {
    if (argc != 2 || (std::string(argv[1]) != "pass" && std::string(argv[1]) != "fail")) {
        std::cerr << "Usage: pick_place pass|fail (expected result)\n";
        return 2;
    }
    constexpr double tolerance = 0.015; // illustrative position tolerance, metres
    constexpr double tool = p::forearm_length_m + p::gripper_palm_length_m + p::finger_length_m / 2;
    const double actual_tool = physical_tool_length();
    std::cout << std::fixed << std::setprecision(4)
              << "controller tool=" << tool << " m; physical tool=" << actual_tool << " m\n";
    const Target stages[] = {{"grasp", .25, .185}, {"lift", .25, .235}, {"place", .24, .185}};
    bool success = true;
    for (const auto& stage : stages) {
        const double height = stage.z - p::shoulder_height_m;
        const double cosine = (stage.x*stage.x + height*height - p::upper_arm_length_m*p::upper_arm_length_m - tool*tool)
            / (2 * p::upper_arm_length_m * tool);
        if (cosine < -1.0 || cosine > 1.0) {
            std::cerr << stage.name << " target outside controller reach\n";
            return 2;
        }
        const double elbow = -std::acos(cosine);
        const double shoulder = std::atan2(height, stage.x) - std::atan2(tool * std::sin(elbow), p::upper_arm_length_m + tool * std::cos(elbow));
        // Apply the same commanded angles to the changed physical arm in both runs.
        const double tip_x = p::upper_arm_length_m * std::cos(shoulder) + actual_tool * std::cos(shoulder + elbow);
        const double tip_z = p::shoulder_height_m + p::upper_arm_length_m * std::sin(shoulder) + actual_tool * std::sin(shoulder + elbow);
        const double error = std::hypot(tip_x - stage.x, tip_z - stage.z);
        std::cout << stage.name << ": target=(" << stage.x << ", " << stage.z << ") m; tip=("
                  << tip_x << ", " << tip_z << ") m; error=" << error << " m\n";
        if (error > tolerance) {
            success = false;
            std::cout << "FAIL: " << stage.name << " misses the " << tolerance << " m position tolerance; remaining stages skipped\n";
            break;
        }
    }
    if (success) std::cout << "PASS: grasp, lift and place positions reached in the kinematic model\n";
    return success == (std::string(argv[1]) == "pass") ? 0 : 1;
}
