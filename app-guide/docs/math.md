---
id: math
title: "math"
sidebar_label: "math"
---
# Overview

The DALi [math](./math.md) module provides a comprehensive suite of geometric and linear algebra utilities designed to handle coordinate transformations, spatial calculations, and viewport management within the UI framework. These tools form the mathematical backbone for positioning, [rendering](./rendering.md), and animating components within the application environment.

# Defining Spatial Coordinates and Dimensions

UI components rely on precise mathematical representations for layout and sizing. Developers use specific vector and pair types to define these dimensions. The `Vector2`, `Vector3`, and `Vector4` structures provide flexible containers for coordinates and color components. For integer-based dimensions, particularly when managing screen-space pixel coordinates, developers should utilize `Int32Pair` or `Uint16Pair`.

```cpp
Vector3 position(10.0f, 20.0f, 0.0f);
Uint16Pair dimensions(1920u, 1080u);
```

Values stored within these classes can be manipulated using overloaded operators for basic arithmetic. The library ensures that common structures are treated as trivial types through the `IS_TRIVIAL_TYPE` where applicable for performance optimization.

# Managing Visual Transformations

Complex 3D UI effects require the use of linear algebra to calculate object orientation, scaling, and translation. The `Matrix` serves as the primary tool for representing transformations, while the `Matrix3` is available for specialized 3x3 operations. Developers can construct these matrices to perform specific tasks such as setting identities, inverting transformations, or creating matrices from rotation quaternions.

Methods such as `SetTransformComponents(const Vector3 &, const Quaternion &, const Vector3 &)` and `GetTransformComponents(Vector3 &, Quaternion &, Vector3 &) const` allow for the direct manipulation and retrieval of position, scale, and rotation data. For high-performance needs, developers can use `OrthoNormalize()` to ensure matrix axes remain orthogonal and unit-length.

```cpp
Matrix transform;
Vector3 scale(1.0f, 1.0f, 1.0f);
Vector3 position(100.0f, 50.0f, 0.0f);
Quaternion rotation(Radian(0.0f), Vector3(0.0f, 0.0f, 1.0f));
transform.SetTransformComponents(scale, rotation, position);
```

Rotation states are primarily handled via the `Quaternion`. This class encapsulates rotation mathematics and provides robust support for spherical linear interpolation, which is essential for smooth animation between two states using `Slerp(const Quaternion &, const Quaternion &, float)`.

# Handling Rotations and Angles

Angular data must be handled consistently throughout an application to avoid conversion errors. DALi provides the `Radian` and `Degree` to explicitly define the units of measurement for angles. The `AngleAxis` is also available to define a rotation as a specific angle around a defined vector axis.

```cpp
Degree degrees(90.0f);
Radian radians(degrees);
Vector3 axis(0.0f, 0.0f, 1.0f);
AngleAxis rotation(radians, axis);
```

When working with rotational data, developers can easily convert between these types. For instance, the `Degree::Degree(float)` can accept a `Radian` as an argument to handle necessary conversions automatically.

# Rectangular Region Logic

Layout management and input hit-testing depend on the `Rect` to define spatial boundaries. This structure provides functionality to manage coordinates, width, and height, allowing for operations such as intersection tests and boundary checks.

Methods including `Intersects(const Rect< T > &) const` and `Contains(const Rect< T > &) const` are fundamental for detecting if a pointer event falls within a specific component's bounds. The `Merge(const Rect< T > &)` and `Inset(T, T)` allow for the dynamic calculation of bounding regions based on padding or child component layouts.

```cpp
Rect<float> pointRect(10.0f, 10.0f, 1.0f, 1.0f);
Rect<float> boundaryRect(0.0f, 0.0f, 100.0f, 100.0f);
bool isIntersecting = boundaryRect.Intersects(pointRect);
```

# Performing Advanced Geometric Calculations

The module supports sophisticated geometric operations, including dot products, cross products, and vector normalization. These operations are accessible via the standard vector classes. The `Dot(const Vector3 &) const` and `Cross(const Vector3 &) const` allow for calculating relationships between vectors, such as projection or the perpendicular axis. 

For 4D vector scenarios, developers should use `Dot4(const Vector4 &) const` to perform full-dimension dot products. Furthermore, developers can leverage matrix inversion and transpose operations to solve complex spatial equations.

```cpp
Vector3 v1(1.0f, 0.0f, 0.0f);
Vector3 v2(0.0f, 1.0f, 0.0f);
Vector3 normal = v1.Cross(v2);
```

# Utility and Randomization Tools

Maintaining numerical precision is critical in UI rendering, especially when comparing floating-point results. The `Epsilon` provides compile-time templates to assist in calculating machine precision for safe floating-point comparisons.

For dynamic UI elements that require randomized behavior, such as particle systems or decorative animations, the `Random` provides helper functions. The `Range(float, float)` returns a random float between two values, while the `Axis()` generates a normalized vector pointing in a random 3D direction.

```cpp
float duration = Random::Range(0.5f, 2.0f);
```

---

> 🔗 **API Reference**: [View Original Documentation](https://dummy-doxygen.tizen.org/dali/math)
