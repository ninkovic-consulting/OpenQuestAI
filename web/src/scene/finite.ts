// A guard at the head of the post chain: any colour channel that is NaN,
// infinite or negative becomes 0 before the tilt-shift and bloom blurs can
// spread it. One bad pixel would otherwise black out the whole frame.

import { BlendFunction, Effect } from "postprocessing";

const fragmentShader = /* glsl */ `
  // NaN fails every comparison, so it falls to zero along with infinities and negatives.
  float finite(const in float v) {
    return v >= 0.0 && v <= 65504.0 ? v : 0.0;
  }
  void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
    outputColor = vec4(finite(inputColor.r), finite(inputColor.g), finite(inputColor.b), finite(inputColor.a));
  }
`;

export class FiniteEffect extends Effect {
  constructor() {
    // SRC writes the result as is: a blend would mix the bad input back in, and NaN times zero is still NaN.
    super("FiniteEffect", fragmentShader, { blendFunction: BlendFunction.SRC });
  }
}
