---
id: image-view
title: "image-view"
sidebar_label: "image-view"
---
## Overview

ImageView is a UI component used to display static image resources like PNG, JPEG, and SVG files within a DALi application layout. It acts as a specialized container that manages the loading, decoding, and [rendering](./rendering.md) of visual content, allowing developers to integrate graphical assets directly into the application interface.

## Creating and Configuring Images

An image resource is defined by its source location, which the component handles through URL-based identification. Developers can instantiate the component and immediately assign a target asset or a fallback mechanism to maintain a consistent UI state during the asynchronous loading process.

```cpp
ImageView imageView = ImageView::New("image_source.png");
imageView.SetPlaceholderUrl("placeholder.png");
```

The primary resource is assigned via the `SetResourceUrl` method`SetResourceUrl(const Dali::String &)`, which informs the engine which file to fetch. If a transitionary visual is desired while the primary asset is being prepared, `SetPlaceholderUrl` can be used to display a temporary alternative.`SetPlaceholderUrl(const Dali::String &)` Both methods are chainable, enabling concise initialization. To refresh the current content manually without re-instantiating the object, the `Reload` method can be invoked.`Reload()`

## Layout and Sizing Control

The rendering of an image within its assigned container space is managed through various fitting and sampling strategies. These ensure that assets maintain their visual integrity regardless of the parent view's dimensions.

```cpp
ImageView imageView = ImageView::New();
imageView.SetFittingMode(FittingMode::Type::FIT_KEEP_ASPECT_RATIO);
imageView.SetDesiredWidth(100);
imageView.SetDesiredHeight(100);
```

The `SetFittingMode` method defines how the texture behaves when its aspect ratio differs from the container.`SetFittingMode(FittingMode::Type)` Options range from stretching to fill the area entirely, to preserving the aspect ratio and cropping the overflow. Scaling quality is further refined by `SetSamplingMode`, which determines the filtering applied during rasterization.`SetSamplingMode(SamplingMode::Type)` For performance optimization, developers can provide rasterization hints using `SetDesiredWidth` and `SetDesiredHeight`.`SetDesiredWidth(int)``SetDesiredHeight(int)` Finally, setting `SetImageLoadWithViewSize` allows the engine to adapt the loading process to match the actual size of the View, reducing unnecessary memory overhead.`SetImageLoadWithViewSize(bool)`

## Advanced Visual Effects

Beyond basic display, the framework supports a range of modifications to the image output, such as color tinting, sub-region selection, and sophisticated masking.

```cpp
ImageView imageView = ImageView::New();
imageView.SetImageColor(UiColor(1.0f, 0.0f, 0.0f, 0.5f));
imageView.SetAlphaMaskUrl("mask.png");
imageView.SetMaskingMode(MaskingType::Type::MASKING_ON_RENDERING);
```

To modify the visual appearance without altering the source file, `SetImageColor` applies a color multiplier to the rendered output.`SetImageColor(const UiColor &)` When only a portion of the source image is required, `SetPixelArea` provides a way to crop the texture to a specific region of interest.`SetPixelArea(const Vector4 &)` For complex shapes, `SetAlphaMaskUrl` defines a mask, and `SetMaskingMode` determines whether this mask is processed during the initial load or applied dynamically during the rendering phase.`SetAlphaMaskUrl(const Dali::String &)``SetMaskingMode(MaskingType::Type)` For UI elements that require flexible resizing, `SetNPatchBorder` manages the insets for N-patch [images](./images.md).`SetNPatchBorder(const Vector4 &)`

## Resource Loading and Lifecycle Management

Efficient memory usage is critical, and the component provides several policies to dictate how textures are cached and managed during the application lifecycle.

```cpp
ImageView imageView = ImageView::New();
imageView.SetLoadPolicy(LoadPolicy::Type::IMMEDIATE);
imageView.SetReleasePolicy(ReleasePolicy::Type::DETACHED);
```

The `SetLoadPolicy` determines if an image fetches its data immediately or waits until the View is attached to the scene.`SetLoadPolicy(LoadPolicy::Type)` Similarly, `SetReleasePolicy` governs when the texture should be purged from memory—whether it stays indefinitely, is released upon detachment, or is destroyed along with the View.`SetReleasePolicy(ReleasePolicy::Type)` Performance-sensitive applications can utilize `SetSynchronousLoading` for immediate blocking loads, or `SetFastTrackUpload` to expedite the transfer of decoded textures to the GPU.`SetSynchronousLoading(bool)``SetFastTrackUpload(bool)`

## Handling State and Signals

Applications can monitor the readiness of assets to coordinate complex UI interactions or display transitions once an image is available.

```cpp
class MyHandler
{
public:
  void OnResourceReady(ImageView view)
  {
  }
};

ImageView imageView = ImageView::New();
MyHandler handler;
imageView.ResourceReadySignal().Connect(&handler, &MyHandler::OnResourceReady);
```

The `ResourceReadySignal` provides a reliable mechanism to execute logic only after the resource is prepared and fully rendered.`ResourceReadySignal()` This is essential for triggering animations or secondary UI updates that depend on the existence of the visual. Developers can check the current state at any time by retrieving the `GetLoadingStatus`, which indicates whether the resource is preparing, ready, or has encountered a failure.`GetLoadingStatus()`

## Related Sub-Components

- `[image-view-impl](./image-view-impl.md)`: Provides internal implementation details and infrastructure for the image display system. → See: [image-view-impl]
- `[image-view-properties](./image-view-properties.md)`: Defines the declarative attribute configurations and property indices used to control component state. → See: [[image-view-properties](./image-view-properties.md)]

---

> 🔗 **API Reference**: [View Original Documentation](https://dummy-doxygen.tizen.org/dali/image-view)
