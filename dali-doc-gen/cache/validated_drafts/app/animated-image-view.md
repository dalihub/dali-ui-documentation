# Overview

AnimatedImageView is a specialized UI component designed for rendering and controlling animated GIF and WEBP media files within your application layout. It provides a robust set of controls for managing the lifecycle, playback state, and visual presentation of complex animated image resources.

# Getting Started

The component follows the Factory pattern for instantiation. You create a new instance and add it to an existing container in your view hierarchy to render content on the screen.

```cpp
AnimatedImageView animatedImageView = AnimatedImageView::New("image_url.gif");
parentView.Add(animatedImageView);
```

The view is managed as a handle. You can retrieve existing instances by downcasting from base handles using the downcast method.`DownCast(BaseHandle)`

# Loading and Resource Management

Configuring the source of your media is fundamental to displaying content. You may set a single resource URL for a standard file, or provide an array of URLs to handle frame-by-frame animation sequences.`SetResourceUrl(const Dali::String &)` `SetResourceUrls(const Dali::Vector< Dali::String > &)`

To optimize performance and memory usage, you can define how and when the image data is fetched. Loading can be triggered immediately upon creation or deferred until the view is attached to the scene.`SetLoadPolicy(LoadPolicy::Type)` `LoadPolicy::IMMEDIATE` `LoadPolicy::ATTACHED`

Placeholder assets are useful for maintaining a polished UI while the actual animation resource is being fetched.`SetPlaceholderUrl(const Dali::String &)` You can track the current health of the loading process through the loading status query.`GetLoadingStatus()`

```cpp
AnimatedImageView animatedImageView = AnimatedImageView::New();
animatedImageView.SetLoadPolicy(LoadPolicy::IMMEDIATE);
animatedImageView.SetPlaceholderUrl("placeholder.png");
```

# Playback Control and State

The component offers granular control over animation execution. You can start, pause, or stop the playback at any time, or jump to a specific point in the sequence for interactive features.`Play()` `Pause()` `Stop()` `JumpToFrame(int)`

Animation speed can be adjusted dynamically using a multiplier to increase or decrease the visual playback rate.`SetFrameSpeedFactor(float)` Furthermore, you can define the total number of times the animation should cycle before ending.`SetLoopCount(int)`

```cpp
animatedImageView.Play();
animatedImageView.SetFrameSpeedFactor(2.0f);
```

# Visual Configuration and Styling

You can modify the appearance of the rendered animation to fit your application theme. This includes applying color modulation, defining fitting modes to control how the image scales within its bounds, and configuring alpha transparency settings.`SetImageColor(const UiColor &)` `SetFittingMode(FittingMode::Type)` `SetPreMultipliedAlpha(bool)`

For advanced layouts, you can extract specific sub-regions of an image using pixel area coordinates, which is useful for sprite sheets or dynamic cropping.`SetPixelArea(const Vector4 &)` Alpha masking is also supported, allowing you to define a shape through which the animation is displayed.`SetAlphaMaskUrl(const Dali::String &)` `SetMaskingMode(MaskingType::Type)`

```cpp
animatedImageView.SetImageColor(UiColor(1.0f, 1.0f, 1.0f, 1.0f));
animatedImageView.SetFittingMode(FittingMode::FILL);
animatedImageView.SetPixelArea(Vector4(0.0f, 0.0f, 0.5f, 0.5f));
```

# Memory and Performance Optimization

High-performance applications require careful management of image resources. You can tune the memory footprint by setting the number of frames to cache and the batch size for pre-loading operations.`SetCacheSize(int)` `SetBatchSize(int)`

For scenarios where blocking the main thread is acceptable to ensure immediate rendering, synchronous loading can be enabled.`SetSynchronousLoading(bool)` Additionally, setting desired width and height hints helps the image loader perform more efficient down-scaling during the decoding process.`SetDesiredWidth(int)` `SetDesiredHeight(int)`

```cpp
animatedImageView.SetCacheSize(10);
animatedImageView.SetBatchSize(5);
```

# Event Handling

The component emits signals to coordinate your application logic with the internal state of the animation. You can listen for the successful loading of resources to transition UI states, or detect when an animation sequence has completed all requested loops.`ResourceReadySignal()` `AnimationFinishedSignal()`

```cpp
animatedImageView.AnimationFinishedSignal().Connect(this, &MyHandler::OnAnimationFinished);
```

# Related Sub-Components

The internal implementation details of this component are managed by the associated implementation module. → See: [animated-image-view-impl]

Supporting enumerations and type definitions that govern the behavior of the view are housed in a dedicated types module. → See: [animated-image-view-types]

Property indices and configurations used for fine-grained, data-driven styling are defined in the property configuration module. → See: [animated-image-view-properties]