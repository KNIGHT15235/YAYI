# 围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。


## 研究范围与证据

本综述检索并去重保留 **120 篇文献**。来源为公开可核查的学术记录；文献存在性/元数据核对与结论事实核验分别记录。正文按可取得的摘要或正文论证，未取得全文的文献不声称完成全文精读，不补造实验数值。

## 范围界定与核心术语定义

本次综述聚焦于2020至2026年间发表的光学遥感图像变化检测方法。变化检测旨在通过分析同一地理区域在不同时间获取的已配准图像，识别地表发生的“感兴趣的变化”，并输出二值变化图。光学遥感图像主要指可见光及近红外波段传感器获取的影像，涵盖从中分辨率（如Sentinel-2）到甚高分辨率（如PlanetScope、航空影像）的数据。 [51](https://arxiv.org/abs/2204.08454) [35](fixtures/BIT-2103.00208.pdf) [1](https://doi.org/10.1109/tgrs.2021.3130842) [7](https://doi.org/10.3390/rs16071274)

在本次纳入的文献样本中，方法架构呈现多样化。例如，有研究采用基于孪生网络的编码器-解码器结构来提取和融合双时相特征。同时，Transformer注意力机制被引入以建模长程依赖和时序交互，例如有研究构建了变化强度令牌来完成时序信息交互。此外，Mamba等状态空间模型也开始被探索用于协同建模局部细节与全局特征。 [3](https://doi.org/10.3390/rs15040928) [90](https://doi.org/10.3390/rs16030572) [45](https://doi.org/10.3390/rs14092228) [100](https://doi.org/10.3390/rs18132226) [117](https://doi.org/10.3390/rs18010108)

为应对标注数据稀缺的挑战，多种学习范式被提出。无监督方法通过建模像素与其空间上下文的线性关系或利用生成对抗网络来避免使用标注数据。半监督方法则利用大量未标注图像，通过设计无监督损失（如一致性正则化）来辅助训练。弱监督方法尝试通过分析边缘图差异等方式以较低成本获取部分真值。 [1](https://doi.org/10.1109/tgrs.2021.3130842) [106](https://doi.org/10.3390/rs12132098) [51](https://arxiv.org/abs/2204.08454) [61](https://doi.org/10.3390/rs12233907) [12](https://doi.org/10.3390/rs17020178)

研究者们设计了多种专用模块以应对特定挑战。例如，有方法采用注意力机制和边缘感知模块来提升边界精度；有工作利用频率域信息（如离散余弦变换）来增强特征表示；还有研究提出差异门控交互模块，以粗预测为语义先导来抑制伪变化并恢复细微变化区域。 [27](https://doi.org/10.3390/rs18020261) [21](https://doi.org/10.3390/rs15215243) [18](https://doi.org/10.3390/rs14194895) [14](https://doi.org/10.3390/rs18162763) [66](https://doi.org/10.2139/ssrn.7230761)

综合来看，2020-2026年间光学遥感变化检测领域呈现出架构融合（CNN、Transformer、Mamba）、范式扩展（全监督到半/弱/无监督）以及问题导向的专用模块设计三大趋势。然而，基于现有摘要证据，缺乏在统一基准和相同实验设置下的直接性能比较，因此无法断言某种架构或范式普遍更优。未来研究需关注在复杂场景下的模型鲁棒性、对成像风格差异的泛化能力，并致力于建立更公平、可比的评估基准。 [8](https://doi.org/10.3390/rs16050804) [100](https://doi.org/10.3390/rs18132226) [6](https://doi.org/10.3390/rs18152523) [27](https://doi.org/10.3390/rs18020261) [9](https://doi.org/10.36227/techrxiv.14069714.v1)

## 主流方法分类与演进脉络

在2020-2026年间，基于孪生网络（Siamese Network）的深度学习架构被用于光学遥感变化检测。这类方法通常将变化检测视为一个二值语义分割任务，通过共享权重的双分支网络分别提取双时相图像的特征，然后进行差异计算和融合以生成变化图。例如，有研究在2021年提出基于深度孪生语义分割网络的监督变化检测方法，直接学习从图像对中提取特征。后续工作在此基础上不断演进，通过引入注意力机制、多尺度特征融合以及设计专门的差异增强模块来提升性能。 [73](https://doi.org/10.3390/rs13173394) [28](https://doi.org/10.3390/rs13224597) [86](https://doi.org/10.3390/rs14071580) [5](https://doi.org/10.3390/rs16101665)

本次纳入的2024—2025年文献已探索基于状态空间模型（State-Space Model）的Mamba架构在变化检测中的应用。这些方法旨在结合全局特征提取能力和线性计算复杂度。例如，有2024年的工作提出DC-Mamba网络，通过引入边缘特征增强块和双流状态空间块来提升对复杂变化区域的检测能力。另一项2025年的研究则探索了Mamba架构在U形变化检测网络中的应用潜力。 [62](https://doi.org/10.3390/rs16224186) [22](https://doi.org/10.1117/1.jrs.19.034513) [40](https://doi.org/10.3390/rs16214068)

除了网络架构的创新，研究也关注于应对不同监督程度的挑战。根据2024年的一篇综述，变化检测方法可依据学习范式分为全监督、半监督、弱监督和无监督等类别。该综述指出，不完全监督（包括半监督和弱监督）的变化检测仍处于起步阶段，需要深入研究。同时，自监督学习和基础模型（Foundation Models）的发展为变化检测提供了新的视角和工具。具体实践上，有2025年的工作提出了一种结合数据增强和自适应阈值更新的半监督方法，以应对标注数据有限的场景。 [8](https://doi.org/10.3390/rs16050804) [12](https://doi.org/10.3390/rs17020178) [13](https://doi.org/10.1109/igarss53475.2024.10640593) [4](https://doi.org/10.3390/rs17030369)

针对变化检测中的具体挑战，如伪变化和边界模糊，研究者设计了多种专用模块。这些模块旨在增强差异信息、抑制背景干扰并提升细节恢复能力。例如，有2023年的方法提出多尺度特征减法融合模块来减少冗余伪变化特征。2026年的研究则设计了差异门控交互模块，基于差异幅度生成变化相关门来抑制伪变化并保留真实变化信号。此外，还有工作通过引入边缘感知模块或边缘高斯聚合模块来改善变化边界的完整性。 [46](https://doi.org/10.3390/rs15153740) [14](https://doi.org/10.3390/rs18162763) [18](https://doi.org/10.3390/rs14194895) [6](https://doi.org/10.3390/rs18152523)

综合来看，本次文献样本显示，2020-2026年光学遥感变化检测方法呈现多样化发展，核心趋势是从依赖卷积神经网络向结合注意力机制、Transformer以及新兴Mamba架构演进，并积极探索在不同监督程度下的解决方案。然而，现有证据主要来自单篇方法提案的摘要，缺乏在统一基准和相同实验设置下的直接性能比较。因此，无法从提供的证据中得出某一类方法“普遍优于”另一类的领域级强断言。未来的研究建议包括：深入探索不完全监督范式，系统评估基础模型在变化检测任务中的适应能力，并在公开数据集上建立更公平、可复现的比较基准以推动领域发展。 [8](https://doi.org/10.3390/rs16050804) [67](https://arxiv.org/abs/2006.05612) [20](https://doi.org/10.3390/rs15082092) [62](https://doi.org/10.3390/rs16224186) [22](https://doi.org/10.1117/1.jrs.19.034513)

## 方法机制、适用条件与局限性比较

针对高分辨率遥感图像变化检测中计算资源消耗大的问题，部分研究设计了轻量化的网络架构。例如，LightCDNet采用MobileNetV2作为孪生编码器的特征提取器以降低计算成本，并在LEVIR-CD和WHU-CD两个建筑变化检测数据集上报告了较高的F1分数。同样，3M-CDNet通过设计仅需约3.12M参数的轻量网络，旨在缓解数据量有限导致的过拟合问题，从而提升泛化能力。 [3](https://doi.org/10.3390/rs15040928) [9](https://doi.org/10.36227/techrxiv.14069714.v1)

为了应对输入图像存在分辨率差异或未精确配准的实际情况，有方法提出了专门的网络模块。RACDNet在第一阶段使用轻量级超分辨率网络重建高质量的双时相图像，第二阶段则在孪生-UNet架构中嵌入可变形卷积单元，以实现双时相深度特征的对齐，从而提取更鲁棒的差异特征。 [17](https://doi.org/10.3390/rs14184527)

Transformer架构因其强大的全局上下文建模能力而被引入变化检测任务。SiamixFormer采用具有分层Transformer架构的孪生编码器，并使用时序Transformer进行特征融合，以维持大的感受野并融合时序特征。VcT模型则通过挖掘可靠的、未变化的背景上下文信息来学习双时相图像的一致性表示，以辅助变化检测。 [23](https://doi.org/10.1080/01431161.2023.2225228) [74](https://doi.org/10.1109/tgrs.2023.3327139)

近期，基于视觉基础模型（如SAM）和状态空间模型（如Mamba）的方法成为新的探索方向。这些方法设计专门的模块来提取与融合变化特征。例如，SAM-MSCD通过双时相特征交互模块（BIM）和变化特征增强模块（CFEM）来增强变化感知，并采用了参数高效的微调策略（如低秩适应）。而Mamba架构则因其线性计算复杂性和长程依赖建模能力受到关注，被提出以应对CNN感受野有限和Transformer计算复杂的问题。 [47](https://doi.org/10.3390/rs18030506) [41](https://doi.org/10.3390/rs16193651) [22](https://doi.org/10.1117/1.jrs.19.034513)

综合来看，在本次样本中，不同方法针对特定的数据特性或应用限制提出了相应的机制。轻量化网络适用于计算资源受限的场景；特征对齐与超分辨率模块针对图像配准和分辨率不一致问题；Transformer和基础模型侧重于提升全局语义理解和特征表示能力；而Mamba类架构则尝试在长程建模和计算效率间取得平衡。然而，由于缺乏统一的实验基准和可比较的量化结果，无法从现有证据中推断这些不同路线之间的绝对性能优劣。未来研究需要更系统地在相同数据集和评估协议下进行比较，并详细报告在不同地物类型和复杂场景下的具体表现与局限。 [3](https://doi.org/10.3390/rs15040928) [17](https://doi.org/10.3390/rs14184527) [23](https://doi.org/10.1080/01431161.2023.2225228) [47](https://doi.org/10.3390/rs18030506) [41](https://doi.org/10.3390/rs16193651)

## 常用数据集、评价指标与实验设置

在2020-2026年的光学遥感变化检测研究中，LEVIR-CD、SYSU-CD和WHU-CD是多个研究中常用的公开数据集。例如，LEVIR-CD数据集由1024×1024像素的双时相谷歌地球图像对构成，包含超过3.1万个独立标注的变化实例。SYSU-CD被描述为更复杂的多元变化类型数据集，WHU-CD也被列为常用数据集。这些数据集为不同方法提供了性能评估基础，但各研究的实验设置和数据划分存在差异。 [63](https://doi.org/10.3390/rs12101662) [54](https://doi.org/10.3390/rs14194972) [30](https://doi.org/10.2139/ssrn.7312323) [85](https://doi.org/10.3390/rs18152491)

F1分数和交并比是评估变化检测模型性能常用的指标。多项研究在LEVIR-CD、SYSU-CD、WHU-CD等数据集上报告这两个指标。例如，有方法在LEVIR-CD上报告了约91.78%的F1分数。在SYSU-CD上，不同方法分别报告了约82.55%的F1分数和约70.37%的IoU。然而，由于各研究的实验设置和数据划分存在差异，这些指标无法对不同方法进行直接、可比的定量排名。 [114](https://doi.org/10.3390/rs15102645) [54](https://doi.org/10.3390/rs14194972) [85](https://doi.org/10.3390/rs18152491) [30](https://doi.org/10.2139/ssrn.7312323)

典型的实验设置通常遵循监督学习范式，使用公开数据集的既定划分进行训练、验证和测试。为了提升模型鲁棒性和缓解过拟合，部分研究采用了在线数据增强和Dropout正则化等策略。此外，针对变化检测中正负样本不平衡的挑战，一些方法引入了Dice损失函数来优化模型训练。 [9](https://doi.org/10.36227/techrxiv.14069714.v1) [36](https://doi.org/10.3390/rs13245152) [4](https://doi.org/10.3390/rs17030369) [46](https://doi.org/10.3390/rs15153740)

现有评价体系可能存在一些缺口。尽管F1和IoU是通用指标，但它们可能无法充分反映模型在特定挑战下的表现，例如对细小目标变化的检测能力、对边界细节的保留程度，以及对由光照、季节或轻微配准误差引起的伪变化的抑制效果。部分研究通过可视化结果或设计专门模块（如针对伪变化抑制）来间接反映这些方面，但缺乏标准化的针对性评价指标。 [18](https://doi.org/10.3390/rs14194895) [58](https://doi.org/10.3390/rs15164095) [30](https://doi.org/10.2139/ssrn.7312323) [54](https://doi.org/10.3390/rs14194972) [14](https://doi.org/10.3390/rs18162763)

综合来看，LEVIR-CD、SYSU-CD和WHU-CD是2020-2026年间光学遥感变化检测领域最主流的评估数据集，F1分数和IoU是核心评价指标。然而，基于提供的摘要证据，无法对不同方法在这些数据集上的性能进行直接、可比的定量排名，因为各研究的实验设置、数据划分和报告的具体数值存在差异。未来的研究建议在报告结果时，除了通用指标，还应考虑设计或报告针对复杂场景（如细小目标、边界精度、伪变化抑制）的细粒度评估方式，以更全面地衡量模型的实际应用能力。 [63](https://doi.org/10.3390/rs12101662) [90](https://doi.org/10.3390/rs16030572) [85](https://doi.org/10.3390/rs18152491) [30](https://doi.org/10.2139/ssrn.7312323) [14](https://doi.org/10.3390/rs18162763)

## 当前研究的局限与未来方向

当前光学遥感变化检测方法在处理高分辨率图像的复杂纹理和细节时仍面临挑战。根据一项2024年的研究，传统基于像素和对象的方法仅适用于中低分辨率图像，而深度学习方法在融合深浅层差异特征信息与注意力机制时，常出现融合不一致和模型训练困难的问题，导致变化区域与不变区域的区分、边缘检测和小目标检测存在误差。该研究认为这些局限在处理高分辨率图像的复杂场景时尤为突出。 [5](https://doi.org/10.3390/rs16101665)

尽管全监督学习在变化检测中取得了显著进展，但其对大规模标注数据的依赖构成了主要局限。相比之下，自监督学习无需显式训练标签即可提取有意义的数据表征，为解决标注数据稀缺问题提供了潜在途径。然而，在复杂的城市环境、小尺度变化和精细边界检测方面，自监督方法仍面临挑战。 [11](https://doi.org/10.3390/rs17152717) [8](https://doi.org/10.3390/rs16050804)

现有模型在利用基础模型的知识和可扩展性方面存在不足，常常忽视过滤不变背景信息的重要性，导致未过滤的令牌干扰模型性能。同时，直接将大规模预训练视觉基础模型应用于遥感变化检测任务时，领域知识差异往往导致结果不理想，这凸显了有效适配基础模型知识的必要性。 [32](https://doi.org/10.21203/rs.3.rs-7112910/v1) [4](https://doi.org/10.3390/rs17030369)

在数据层面，领域偏移问题限制了预训练模型在实际应用中的性能。由于数据隐私、安全和传输限制，特定变化检测领域可能无法访问源域数据，这使得现有的无监督域适应方法几乎失效。因此，开发仅使用预训练源模型和未标记目标数据的源自由无监督域适应方法，是应对现实世界数据分布差异的关键方向。 [7](https://doi.org/10.3390/rs16071274)

综合来看，基于本次文献样本的分析，当前研究在方法、数据和应用层面存在多重局限。未来研究应着重探索不完全监督（如半监督、弱监督）和自监督学习范式，以降低对大量标注数据的依赖。同时，有效适配和利用视觉基础模型的通用知识，并开发能够处理跨域、多分辨率和复杂成像条件差异的鲁棒模型，是填补现有研究空白、推动领域发展的可行方向。需要指出的是，以上结论主要基于摘要级别的证据，缺乏对具体实验设置、完整性能指标和跨方法统一基准比较的细节支持。 [8](https://doi.org/10.3390/rs16050804) [11](https://doi.org/10.3390/rs17152717) [7](https://doi.org/10.3390/rs16071274) [4](https://doi.org/10.3390/rs17030369) [32](https://doi.org/10.21203/rs.3.rs-7112910/v1)

## 综合结论与建议

综合本次文献调研，2020-2026年间光学遥感图像变化检测领域呈现出方法架构多样化与学习范式扩展的特征。在本次样本中，方法路线涵盖了基于卷积神经网络和孪生网络的架构、结合Transformer注意力机制以建模长程依赖的方法，以及探索Mamba等状态空间模型以协同局部细节与全局特征的研究。同时，为应对标注数据稀缺的挑战，研究涵盖了全监督、半监督、弱监督及无监督等多种学习范式，其中不完全监督的范式被指出仍处于起步阶段，需要深入研究。 [8](https://doi.org/10.3390/rs16050804) [20](https://doi.org/10.3390/rs15082092) [45](https://doi.org/10.3390/rs14092228) [100](https://doi.org/10.3390/rs18132226) [12](https://doi.org/10.3390/rs17020178)

尽管新方法不断涌现，但现有证据主要来自单篇方法提案的摘要，缺乏在统一基准、相同实验设置和完整性能指标下的直接比较。因此，无法从提供的证据中得出某一类架构或范式“普遍优于”另一类的领域级强断言。例如，虽然Transformer和Mamba架构被报告能改善全局建模或计算效率，但CNN-based方法同样在特定数据集上报告了有竞争力的结果。性能优劣的判断受到实验设置、数据集划分和报告指标差异的严重限制。 [38](https://doi.org/10.3390/rs18152573) [67](https://arxiv.org/abs/2006.05612) [9](https://doi.org/10.36227/techrxiv.14069714.v1) [114](https://doi.org/10.3390/rs15102645)

当前研究在应对实际应用挑战方面仍存在明确局限。首先，模型对由光照、季节、成像差异引起的伪变化的抑制能力仍需加强，部分研究通过设计专门的风格适应、差异门控或伪变化抑制模块来应对。其次，在有限标注数据下，半监督和弱监督方法的有效性高度依赖于一致性正则化、伪标签质量平衡等策略的设计。此外，直接将大规模视觉基础模型应用于遥感变化检测任务时，面临领域知识差异和任务适配的挑战。 [6](https://doi.org/10.3390/rs18152523) [14](https://doi.org/10.3390/rs18162763) [30](https://doi.org/10.2139/ssrn.7312323) [12](https://doi.org/10.3390/rs17020178) [4](https://doi.org/10.3390/rs17030369)

基于现有证据的限制，对未来研究提出以下审慎建议。第一，应致力于构建和采用更统一、全面的评估基准与协议，确保不同方法在相同的数据划分、评价指标（不仅限于F1和IoU，还应包含对边界精度、小目标检测、伪变化抑制的细粒度评估）下进行公平比较。第二，应深入探索标签高效的学习范式，包括半监督、弱监督、自监督以及基础模型的高效适配技术，以降低对大量像素级标注的依赖，并系统评估其在复杂场景下的泛化能力和鲁棒性。第三，鼓励开发能够显式处理多源、多分辨率、未精确配准以及存在显著域偏移的实用化方法，以缩小研究与实际部署之间的差距。 [38](https://doi.org/10.3390/rs18152573) [99](https://doi.org/10.1109/tgrs.2024.3491715) [8](https://doi.org/10.3390/rs16050804) [7](https://doi.org/10.3390/rs16071274) [17](https://doi.org/10.3390/rs14184527)

## 文献集统计与图谱口径

以下统计仅描述本次检索集（120 篇），不代表领域全部文献。年份分布直接统计文献元数据；文献按年份均衡取样并优先保留可读摘要，柱状图不能用于推断领域发文趋势。方法关键词由标题/摘要的明确词项匹配获得，为可重叠标签，不等同于论文主要方法或性能排名。图谱边分别表示文献属于本次研究集、发表年份、标题/摘要提及的方法关键词。

![文献年份分布](figures/corpus_years.png)

![方法关键词分布](figures/corpus_methods.png)

## 纳入文献对照表

|编号|文献|年份|标题/摘要方法关键词|
|---|---|---|---|
|106|[A Classified Adversarial Network for Multi-Spectral Remote Sensing Image Change Detection](https://doi.org/10.3390/rs12132098)|2020|未匹配预设词项|
|96|[A Deep Siamese Network with Hybrid Convolutional Feature Extraction Module for Change Detection Based on Multi-sensor Remote Sensing Images](https://doi.org/10.3390/rs12020205)|2020|卷积网络、孪生网络、注意力机制|
|63|[A Spatial-Temporal Attention-Based Method and a New Dataset for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs12101662)|2020|孪生网络、注意力机制|
|57|[Automatic Monitoring of Mines Mining based on Multitemporal Remote Sensing Image Change Detection](https://doi.org/10.5194/egusphere-egu2020-12012)|2020|未匹配预设词项|
|31|[Change Detection Network of Nearshore Ships for Multi-Temporal Optical Remote Sensing Images](https://doi.org/10.1109/igarss39084.2020.9323388)|2020|未匹配预设词项|
|105|[Change Detection within Remotely Sensed Satellite Image Time Series via Spectral Analysis](https://doi.org/10.3390/rs12234001)|2020|未匹配预设词项|
|67|[Deep Learning for Change Detection in Remote Sensing Images: Comprehensive Review and Meta-Analysis](https://arxiv.org/abs/2006.05612)|2020|未匹配预设词项|
|69|[Deep Learning for Land Cover Change Detection](https://doi.org/10.3390/rs13010078)|2020|未匹配预设词项|
|43|[Kernel Anomalous Change Detection for Remote Sensing Imagery](https://doi.org/10.1109/tgrs.2019.2916212)|2020|未匹配预设词项|
|24|[PGA-SiamNet: Pyramid Feature-Based Attention-Guided Siamese Network for Remote Sensing Orthoimagery Building Change Detection](https://doi.org/10.3390/rs12030484)|2020|孪生网络、注意力机制|
|26|[Self-Supervised Representation Learning for Remote Sensing Image Change Detection Based on Temporal Prediction](https://doi.org/10.3390/rs12111868)|2020|自监督/对比学习|
|76|[TCDNet: Trilateral Change Detection Network for Google Earth Image](https://doi.org/10.3390/rs12172669)|2020|未匹配预设词项|
|103|[Unsupervised Self-training Algorithm Based on Deep Learning for Optical Aerial Images Change Detection](https://arxiv.org/abs/2010.07469)|2020|未匹配预设词项|
|61|[Weakly Supervised Change Detection Based on Edge Mapping and SDAE Network in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs12233907)|2020|半监督/弱监督|
|9|[3M-CDNet: A Universal Powerful Benchmark for Remote Sensing Image Change Detection](https://doi.org/10.36227/techrxiv.14069714.v1)|2021|未匹配预设词项|
|75|[AGCDetNet:An Attention-Guided Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.1109/jstars.2021.3077545)|2021|注意力机制|
|36|[An Efficient Lightweight Neural Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs13245152)|2021|注意力机制|
|28|[Attention-Guided Siamese Fusion Network for Change Detection of Remote Sensing Images](https://doi.org/10.3390/rs13224597)|2021|孪生网络、注意力机制|
|16|[Building Change Detection for Remote Sensing Images Using a Dual-Task Constrained Deep Siamese Convolutional Network Model](https://doi.org/10.1109/lgrs.2020.2988032)|2021|孪生网络|
|119|[Change Capsule Network for Optical Remote Sensing Image Change Detection](https://doi.org/10.3390/rs13142646)|2021|未匹配预设词项|
|59|[Change is Everywhere: Single-Temporal Supervised Object Change Detection in Remote Sensing Imagery](https://arxiv.org/abs/2108.07002)|2021|未匹配预设词项|
|92|[DSA-Net: A novel deeply supervised attention-guided network for building change detection in high-resolution remote sensing images](https://doi.org/10.1016/j.jag.2021.102591)|2021|注意力机制|
|48|[Deep Learning of High-Resolution Aerial Imagery for Coastal Marsh Change Detection: A Comparative Study](https://doi.org/10.20944/preprints202112.0077.v1)|2021|卷积网络|
|73|[Deep Siamese Networks Based Change Detection with Remote Sensing Images](https://doi.org/10.3390/rs13173394)|2021|孪生网络|
|82|[Deep few-shot learning for bi-temporal building change detection](https://arxiv.org/abs/2108.11262)|2021|未匹配预设词项|
|79|[HDFNet: Hierarchical Dynamic Fusion Network for Change Detection in Optical Aerial Images](https://doi.org/10.3390/rs13081440)|2021|卷积网络|
|29|[MRA-SNet: Siamese Networks of Multiscale Residual and Attention for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs13224528)|2021|卷积网络、孪生网络、注意力机制|
|118|[Optical Remote Sensing Image Change Detection Based on Attention Mechanism and Image Difference](https://doi.org/10.1109/tgrs.2020.3033009)|2021|注意力机制|
|111|[Remote Sensing Image Augmentation Based on Text Description for Waterside Change Detection](https://doi.org/10.3390/rs13101894)|2021|未匹配预设词项|
|15|[Remote Sensing Image Change Detection Based on Fully Convolutional Network With Pyramid Attention](https://doi.org/10.1109/igarss47720.2021.9554522)|2021|注意力机制|
|1|[Spatial Context Awareness for Unsupervised Change Detection in Optical Satellite Images](https://doi.org/10.1109/tgrs.2021.3130842)|2021|未匹配预设词项|
|94|[Task-Related Self-Supervised Learning For Remote Sensing Image Change Detection](https://doi.org/10.1109/icassp39728.2021.9414387)|2021|卷积网络、注意力机制、自监督/对比学习|
|109|[A Deeply Supervised Attentive High-Resolution Network for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs15010045)|2022|注意力机制|
|45|[A Network Combining a Transformer and a Convolutional Neural Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs14092228)|2022|Transformer、注意力机制|
|60|[Change Detection for High-Resolution Remote Sensing Images Based on a Multi-Scale Attention Siamese Network](https://doi.org/10.3390/rs14143464)|2022|孪生网络、注意力机制、自监督/对比学习|
|110|[Deep Learning-Based Change Detection in Remote Sensing Images: A Review](https://doi.org/10.3390/rs14040871)|2022|半监督/弱监督|
|93|[Fully Transformer Network for Change Detection of Remote Sensing Images](https://arxiv.org/abs/2210.00757)|2022|Transformer、注意力机制|
|102|[Inferring 3D change detection from bitemporal optical images](https://arxiv.org/abs/2205.15903)|2022|Transformer、孪生网络|
|84|[Learning Pairwise Potential CRFs in Deep Siamese Network for Change Detection](https://doi.org/10.3390/rs14040841)|2022|孪生网络、注意力机制|
|18|[MAEANet: Multiscale Attention and Edge-Aware Siamese Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs14194895)|2022|孪生网络、注意力机制|
|77|[MCTNet: A Multi-Scale CNN-Transformer Network for Change Detection in Optical Remote Sensing Images](https://doi.org/10.23919/fusion52260.2023.10224182)|2022|Transformer、卷积网络|
|78|[MDESNet: Multitask Difference-Enhanced Siamese Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs14153775)|2022|孪生网络|
|104|[MFATNet: Multi-Scale Feature Aggregation via Transformer for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs14215379)|2022|Transformer、注意力机制|
|17|[RACDNet: Resolution- and Alignment-Aware Change Detection Network for Optical Remote Sensing Imagery](https://doi.org/10.3390/rs14184527)|2022|卷积网络、孪生网络、注意力机制|
|54|[Remote Sensing Image-Change Detection with Pre-Generation of Depthwise-Separable Change-Salient Maps](https://doi.org/10.3390/rs14194972)|2022|Transformer、卷积网络、注意力机制|
|51|[Revisiting Consistency Regularization for Semi-supervised Change Detection in Remote Sensing Images](https://arxiv.org/abs/2204.08454)|2022|半监督/弱监督|
|86|[SMD-Net: Siamese Multi-Scale Difference-Enhancement Network for Change Detection in Remote Sensing](https://doi.org/10.3390/rs14071580)|2022|孪生网络、注意力机制|
|72|[Self-Supervised Change Detection in Multiview Remote Sensing Images](https://doi.org/10.1109/tgrs.2021.3089453)|2022|孪生网络、自监督/对比学习|
|88|[SemiSANet: A Semi-Supervised High-Resolution Remote Sensing Image Change Detection Model Using Siamese Networks with Graph Attention](https://doi.org/10.3390/rs14122801)|2022|孪生网络、注意力机制、半监督/弱监督|
|10|[Supervising Remote Sensing Change Detection Models with 3D Surface Semantics](https://arxiv.org/abs/2202.13251)|2022|多模态方法、自监督/对比学习|
|116|[A CNN-Transformer Network Combining CBAM for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs15092406)|2023|Transformer、卷积网络、注意力机制|
|120|[A Full-Scale Connected CNN–Transformer Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs15225383)|2023|Transformer、卷积网络、孪生网络、注意力机制|
|3|[A Lightweight Siamese Neural Network for Building Change Detection Using Remote Sensing Images](https://doi.org/10.3390/rs15040928)|2023|孪生网络|
|20|[A Review of Deep-Learning Methods for Change Detection in Multispectral Remote Sensing Images](https://doi.org/10.3390/rs15082092)|2023|半监督/弱监督|
|114|[A VHR Bi-Temporal Remote-Sensing Image Change Detection Network Based on Swin Transformer](https://doi.org/10.3390/rs15102645)|2023|Transformer、注意力机制|
|83|[Bitemporal Remote Sensing Image Change Detection Network Based on Siamese-Attention Feedback Architecture](https://doi.org/10.3390/rs15174186)|2023|孪生网络、注意力机制|
|95|[DAFNet: A Novel Change-Detection Model for High-Resolution Remote-Sensing Imagery Based on Feature Difference and Attention Mechanism](https://doi.org/10.3390/rs15153896)|2023|孪生网络、注意力机制|
|81|[FERA-Net: A Building Change Detection Method for High-Resolution Remote Sensing Imagery Based on Residual Attention and High-Frequency Features](https://doi.org/10.3390/rs15020395)|2023|孪生网络、注意力机制|
|113|[High-Resolution Remote Sensing Image Change Detection Method Based on Improved Siamese U-Net](https://doi.org/10.3390/rs15143517)|2023|孪生网络|
|19|[High‐resolution optical remote sensing image change detection based on dense connection and attention feature fusion network](https://doi.org/10.1111/phor.12462)|2023|孪生网络、注意力机制|
|107|[MBCNet: Multi-Branch Collaborative Change-Detection Network Based on Siamese Structure](https://doi.org/10.3390/rs15092237)|2023|孪生网络、注意力机制|
|46|[MFSFNet: Multi-Scale Feature Subtraction Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs15153740)|2023|未匹配预设词项|
|21|[Multi-Scale Discrete Cosine Transform Network for Building Change Detection in Very-High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs15215243)|2023|注意力机制|
|25|[Remote Sensing Image Change Detection Based on Deep Multi-Scale Multi-Attention Siamese Transformer Network](https://doi.org/10.3390/rs15030842)|2023|Transformer、卷积网络、孪生网络、注意力机制|
|23|[SiamixFormer: a fully-transformer Siamese network with temporal Fusion for accurate building detection and change detection in bi-temporal remote sensing images](https://doi.org/10.1080/01431161.2023.2225228)|2023|Transformer、孪生网络|
|58|[Spatial-Temporal Semantic Perception Network for Remote Sensing Image Semantic Change Detection](https://doi.org/10.3390/rs15164095)|2023|注意力机制|
|71|[TransY-Net: Learning Fully Transformer Networks for Change Detection of Remote Sensing Images](https://doi.org/10.1109/tgrs.2023.3327253)|2023|Transformer、注意力机制|
|74|[VcT: Visual Change Transformer for Remote Sensing Image Change Detection](https://doi.org/10.1109/tgrs.2023.3327139)|2023|Transformer、注意力机制|
|8|[Advances and Challenges in Deep Learning-Based Change Detection for Remote Sensing Images: A Review through Various Learning Paradigms](https://doi.org/10.3390/rs16050804)|2024|多模态方法、半监督/弱监督、自监督/对比学习|
|44|[An Unsupervised Remote Sensing Image Change Detection Method Based on RVMamba and Posterior Probability Space Change Vector](https://doi.org/10.3390/rs16244656)|2024|状态空间模型|
|108|[Change Detection between Optical Remote Sensing Imagery and Map Data Via Segment Anything Model (SAM)](https://doi.org/10.1109/igarss53475.2024.10642789)|2024|基础模型、多模态方法|
|62|[DC-Mamba: A Novel Network for Enhanced Remote Sensing Change Detection in Difficult Cases](https://doi.org/10.3390/rs16224186)|2024|Transformer、卷积网络、注意力机制、状态空间模型|
|42|[Fine-Grained High-Resolution Remote Sensing Image Change Detection by SAM-UNet Change Detection Model](https://doi.org/10.3390/rs16193620)|2024|基础模型|
|41|[Iterative Mamba Diffusion Change-Detection Model for Remote Sensing](https://doi.org/10.3390/rs16193651)|2024|Transformer、注意力机制、状态空间模型|
|98|[Laddering vision foundation model for remote sensing image change detection](https://doi.org/10.1117/1.jrs.18.036503)|2024|Transformer、基础模型|
|50|[MDANet: A High-Resolution City Change Detection Network Based on Difference and Attention Mechanisms under Multi-Scale Feature Fusion](https://doi.org/10.3390/rs16081387)|2024|孪生网络、注意力机制|
|90|[MSGFNet: Multi-Scale Gated Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs16030572)|2024|孪生网络|
|99|[MineNetCD: A Benchmark for Global Mining Change Detection on Remote Sensing Imagery](https://doi.org/10.1109/tgrs.2024.3491715)|2024|未匹配预设词项|
|5|[Multi-Scale Fusion Siamese Network Based on Three-Branch Attention Mechanism for High-Resolution Remote Sensing Image Change Detection](https://doi.org/10.3390/rs16101665)|2024|孪生网络、注意力机制|
|91|[Multistage Interaction Network for Remote Sensing Change Detection](https://doi.org/10.3390/rs16061077)|2024|未匹配预设词项|
|7|[SFDA-CD: A Source-Free Unsupervised Domain Adaptation for VHR Image Change Detection](https://doi.org/10.3390/rs16071274)|2024|注意力机制、自监督/对比学习|
|33|[Semi-Supervised Remote Sensing Building Change Detection with Joint Perturbation and Feature Complementation](https://doi.org/10.3390/rs16183424)|2024|半监督/弱监督|
|112|[Siamese InternImage for Change Detection](https://doi.org/10.3390/rs16193642)|2024|Transformer、卷积网络、基础模型、孪生网络、注意力机制|
|49|[Siamese Transformer-Based Building Change Detection in Remote Sensing Images](https://doi.org/10.3390/s24041268)|2024|Transformer、孪生网络|
|40|[TTMGNet: Tree Topology Mamba-Guided Network Collaborative Hierarchical Incremental Aggregation for Change Detection](https://doi.org/10.3390/rs16214068)|2024|注意力机制、状态空间模型|
|13|[Time Travelling Pixels: Bitemporal Features Integration with Foundation Model for Remote Sensing Image Change Detection](https://doi.org/10.1109/igarss53475.2024.10640593)|2024|基础模型|
|70|[2DMCG: 2D mamba with change flow guidance for change detection in remote sensing](https://doi.org/10.1177/1088467x251401374)|2025|状态空间模型|
|89|[A Lightweight Remote-Sensing Image-Change Detection Algorithm Based on Asymmetric Convolution and Attention Coupling](https://doi.org/10.3390/rs17132226)|2025|卷积网络、注意力机制|
|56|[A Semantic-Guided Cross-Attention Network for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs17101749)|2025|注意力机制|
|4|[ASS-CD: Adapting Segment Anything Model and Swin-Transformer for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs17030369)|2025|Transformer、基础模型、注意力机制|
|11|[Advancing Self-Supervised Learning for Building Change Detection and Damage Assessment: Unified Denoising Autoencoder and Contrastive Learning Framework](https://doi.org/10.3390/rs17152717)|2025|Transformer、自监督/对比学习|
|34|[Building Change Detection in Aerial Imagery Using End-to-End Deep Learning Semantic Segmentation Techniques](https://doi.org/10.3390/buildings15050695)|2025|Transformer、卷积网络、孪生网络|
|52|[Building change detection via classification in high-resolution aerial imagery](https://doi.org/10.11591/ijai.v14.i5.pp4319-4331)|2025|未匹配预设词项|
|64|[CMSNet: A SAM-Enhanced CNN–Mamba Framework for Damaged Building Change Detection in Remote Sensing Imagery](https://doi.org/10.3390/rs17233913)|2025|卷积网络、基础模型、状态空间模型|
|32|[FMT: Foundation Model-based Transformer for Remote Sensing Change Detection](https://doi.org/10.21203/rs.3.rs-7112910/v1)|2025|Transformer、基础模型、注意力机制|
|2|[HiSTENet: History-Integrated Spatial–Temporal Information Extraction Network for Time Series Remote Sensing Image Change Detection](https://doi.org/10.3390/rs17050792)|2025|未匹配预设词项|
|117|[MSMCD: A Multi-Stage Mamba Network for Geohazard Change Detection](https://doi.org/10.3390/rs18010108)|2025|状态空间模型|
|65|[Perturbation Matters: A Novel Approach for Semi-Supervised Remote Sensing Imagery Change Detection](https://doi.org/10.3390/rs17040576)|2025|半监督/弱监督|
|97|[SAM-FDN: A SAM Fine-Tuning Adaptation Remote Sensing Change Detection Method Based on Fourier Frequency Domain Analysis Difference Reinforcement](https://doi.org/10.3390/rs17233842)|2025|基础模型|
|12|[Semi-Supervised Change Detection with Data Augmentation and Adaptive Thresholding for High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs17020178)|2025|半监督/弱监督|
|87|[Siamese-SAM: Remote Sensing Image Change Detection with Siamese Structure Segment Anything Model](https://doi.org/10.3390/app15073475)|2025|基础模型、孪生网络|
|39|[Sliding-Window Dissimilarity Cross-Attention for Near-Real-Time Building Change Detection](https://doi.org/10.3390/rs17010135)|2025|Transformer、孪生网络、注意力机制|
|22|[VG-Net: a Mamba-based U-shaped network for remote sensing change detection](https://doi.org/10.1117/1.jrs.19.034513)|2025|注意力机制、状态空间模型|
|115|[A Differential-Based Siamese Network Integrating the CSWin Transformer for Rural Land Cover Semantic Change Detection](https://doi.org/10.3390/rs18040557)|2026|Transformer、卷积网络、孪生网络|
|47|[A Multi-Scale Remote Sensing Image Change Detection Network Based on Vision Foundation Model](https://doi.org/10.3390/rs18030506)|2026|基础模型、注意力机制|
|101|[ATCFNet: A Lightweight Cross-Level Attention-Guided High-Resolution Remote Sensing Image Change Detection Network](https://doi.org/10.3390/rs18091306)|2026|注意力机制|
|38|[Change Detection in Remote Sensing Imagery: A Systematic Review of Statistical, Machine Learning, and Deep Learning Methods](https://doi.org/10.3390/rs18152573)|2026|Transformer、孪生网络、扩散模型、注意力机制、半监督/弱监督|
|121|[Cross-Image Feature Interaction Network for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs18050717)|2026|注意力机制|
|14|[Difference-Gated Interaction and Change-Aware Cross-Temporal Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18162763)|2026|注意力机制|
|53|[Frequency-aware dual-domain network for remote sensing optical image change detection](https://doi.org/10.1117/1.jrs.20.018504)|2026|注意力机制|
|68|[Incorporating Directional Relationship Modelling for Building Change Detection from Very-High-Resolution Satellite Images](https://doi.org/10.14358/pers.25-00114r2)|2026|未匹配预设词项|
|55|[Island Building Change Detection in High-Resolution Remote Sensing Images Using Hybrid Attention and Cross-Scale Feature Enhancement](https://doi.org/10.2139/ssrn.7218203)|2026|Transformer、卷积网络、孪生网络、注意力机制|
|30|[Layer-contrast foundation representations for pseudo-change suppression in remote sensing change detection](https://doi.org/10.2139/ssrn.7312323)|2026|未匹配预设词项|
|100|[Locally Adaptive Mamba and Multi-Scale Feature Enhancement for Optical Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18132226)|2026|Transformer、卷积网络、注意力机制、状态空间模型|
|27|[MEANet: A Novel Multiscale Edge-Aware Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs18020261)|2026|自监督/对比学习|
|80|[MS-HySAN: A Hybrid Multi-Scale Siamese Attention Network for Interpretable Change Detection in High-Resolution Satellite Imagery](https://doi.org/10.20944/preprints202605.1851.v1)|2026|卷积网络、孪生网络、注意力机制|
|37|[MSRNet: Mamba-Based Self-Refinement Framework for Remote Sensing Change Detection](https://doi.org/10.3390/rs18071042)|2026|注意力机制、状态空间模型|
|85|[PCINet: A Prior-Guided Correlation Interaction Network for High-Resolution Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18152491)|2026|未匹配预设词项|
|66|[Pseudo-change suppression for remote sensing change detection via intermediate foundation features](https://doi.org/10.2139/ssrn.7230761)|2026|未匹配预设词项|
|6|[Self-Supervised Pre-Training Style Adaptation-Guided Remote Sensing Image Change Detection Network](https://doi.org/10.3390/rs18152523)|2026|自监督/对比学习|

## 参考文献

1. Lukas Kondmann, Aysim Toker, Sudipan Saha, Bernhard Schölkopf et al.. [Spatial Context Awareness for Unsupervised Change Detection in Optical Satellite Images](https://doi.org/10.1109/tgrs.2021.3130842). 2021. DOI: 10.1109/tgrs.2021.3130842

2. Lu Zhao, Ling Wan, Lei Ma, Yiming Zhang. [HiSTENet: History-Integrated Spatial–Temporal Information Extraction Network for Time Series Remote Sensing Image Change Detection](https://doi.org/10.3390/rs17050792). 2025. DOI: 10.3390/rs17050792

3. Haiping Yang, Yuanyuan Chen, Wei Wu, Shiliang Pu et al.. [A Lightweight Siamese Neural Network for Building Change Detection Using Remote Sensing Images](https://doi.org/10.3390/rs15040928). 2023. DOI: 10.3390/rs15040928

4. Chenlong Wei, Xiaofeng Wu, Bin Wang. [ASS-CD: Adapting Segment Anything Model and Swin-Transformer for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs17030369). 2025. DOI: 10.3390/rs17030369

5. Yan Li, Liguo Weng, Min Xia, Kai Hu et al.. [Multi-Scale Fusion Siamese Network Based on Three-Branch Attention Mechanism for High-Resolution Remote Sensing Image Change Detection](https://doi.org/10.3390/rs16101665). 2024. DOI: 10.3390/rs16101665

6. Baocai Zhang, Liang Huang, Bowen Su, Shiyi Zheng et al.. [Self-Supervised Pre-Training Style Adaptation-Guided Remote Sensing Image Change Detection Network](https://doi.org/10.3390/rs18152523). 2026. DOI: 10.3390/rs18152523

7. Jingxuan Wang, Chen Wu. [SFDA-CD: A Source-Free Unsupervised Domain Adaptation for VHR Image Change Detection](https://doi.org/10.3390/rs16071274). 2024. DOI: 10.3390/rs16071274

8. Lukang Wang, Min Zhang, Xu Gao, Wenzhong Shi. [Advances and Challenges in Deep Learning-Based Change Detection for Remote Sensing Images: A Review through Various Learning Paradigms](https://doi.org/10.3390/rs16050804). 2024. DOI: 10.3390/rs16050804

9. Kaiqiang Song, Jie Jiang. [3M-CDNet: A Universal Powerful Benchmark for Remote Sensing Image Change Detection](https://doi.org/10.36227/techrxiv.14069714.v1). 2021. DOI: 10.36227/techrxiv.14069714.v1

10. Isaac Corley, Peyman Najafirad. [Supervising Remote Sensing Change Detection Models with 3D Surface Semantics](https://arxiv.org/abs/2202.13251). 2022.

11. Songxi Yang, Bo Peng, Tang Sui, Meiliu Wu et al.. [Advancing Self-Supervised Learning for Building Change Detection and Damage Assessment: Unified Denoising Autoencoder and Contrastive Learning Framework](https://doi.org/10.3390/rs17152717). 2025. DOI: 10.3390/rs17152717

12. Wuxia Zhang, Xinlong Shu, Siyuan Wu, Songtao Ding. [Semi-Supervised Change Detection with Data Augmentation and Adaptive Thresholding for High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs17020178). 2025. DOI: 10.3390/rs17020178

13. Keyan Chen, Chengyang Liu, Wenyuan Li, Zili Liu et al.. [Time Travelling Pixels: Bitemporal Features Integration with Foundation Model for Remote Sensing Image Change Detection](https://doi.org/10.1109/igarss53475.2024.10640593). 2024. DOI: 10.1109/igarss53475.2024.10640593

14. Lele Li, Panpan Zheng, Liejun Wang, Yuqing Zhou. [Difference-Gated Interaction and Change-Aware Cross-Temporal Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18162763). 2026. DOI: 10.3390/rs18162763

15. Shujun Li, Lianzhi Huo. [Remote Sensing Image Change Detection Based on Fully Convolutional Network With Pyramid Attention](https://doi.org/10.1109/igarss47720.2021.9554522). 2021. DOI: 10.1109/igarss47720.2021.9554522

16. Yi Liu, Chao Pang, Zongqian Zhan, Xiaomeng Zhang et al.. [Building Change Detection for Remote Sensing Images Using a Dual-Task Constrained Deep Siamese Convolutional Network Model](https://doi.org/10.1109/lgrs.2020.2988032). 2021. DOI: 10.1109/lgrs.2020.2988032

17. Juan Tian, Daifeng Peng, Haiyan Guan, Haiyong Ding. [RACDNet: Resolution- and Alignment-Aware Change Detection Network for Optical Remote Sensing Imagery](https://doi.org/10.3390/rs14184527). 2022. DOI: 10.3390/rs14184527

18. Bingjie Yang, Yuancheng Huang, Xin Su, Haonan Guo. [MAEANet: Multiscale Attention and Edge-Aware Siamese Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs14194895). 2022. DOI: 10.3390/rs14194895

19. Daifeng Peng, Chenchen Zhai, Yongjun Zhang, Haiyan Guan. [High‐resolution optical remote sensing image change detection based on dense connection and attention feature fusion network](https://doi.org/10.1111/phor.12462). 2023. DOI: 10.1111/phor.12462

20. Eleonora Jonasova Parelius. [A Review of Deep-Learning Methods for Change Detection in Multispectral Remote Sensing Images](https://doi.org/10.3390/rs15082092). 2023. DOI: 10.3390/rs15082092

21. Yangpeng Zhu, Lijuan Fan, Qianyu Li, Jing Chang. [Multi-Scale Discrete Cosine Transform Network for Building Change Detection in Very-High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs15215243). 2023. DOI: 10.3390/rs15215243

22. Linzhi Su, Yang Qu, Yuji Chen, Xin Cao. [VG-Net: a Mamba-based U-shaped network for remote sensing change detection](https://doi.org/10.1117/1.jrs.19.034513). 2025. DOI: 10.1117/1.jrs.19.034513

23. Amir Mohammadian, Foad Ghaderi. [SiamixFormer: a fully-transformer Siamese network with temporal Fusion for accurate building detection and change detection in bi-temporal remote sensing images](https://doi.org/10.1080/01431161.2023.2225228). 2023. DOI: 10.1080/01431161.2023.2225228

24. Huiwei Jiang, Xiangyun Hu, Kun Li, Jinming Zhang et al.. [PGA-SiamNet: Pyramid Feature-Based Attention-Guided Siamese Network for Remote Sensing Orthoimagery Building Change Detection](https://doi.org/10.3390/rs12030484). 2020. DOI: 10.3390/rs12030484

25. Mengxuan Zhang, Zhao Liu, Jie Feng, Long Liu et al.. [Remote Sensing Image Change Detection Based on Deep Multi-Scale Multi-Attention Siamese Transformer Network](https://doi.org/10.3390/rs15030842). 2023. DOI: 10.3390/rs15030842

26. Huihui Dong, Wenping Ma, Yue Wu, Jun Zhang et al.. [Self-Supervised Representation Learning for Remote Sensing Image Change Detection Based on Temporal Prediction](https://doi.org/10.3390/rs12111868). 2020. DOI: 10.3390/rs12111868

27. Tao Chen, Linjin Huang, Wenyi Zhao, Shengjie Yu et al.. [MEANet: A Novel Multiscale Edge-Aware Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs18020261). 2026. DOI: 10.3390/rs18020261

28. Puhua Chen, Lei Guo, Xiangrong Zhang, Kai Qin et al.. [Attention-Guided Siamese Fusion Network for Change Detection of Remote Sensing Images](https://doi.org/10.3390/rs13224597). 2021. DOI: 10.3390/rs13224597

29. Xin Yang, Lei Hu, Yongmei Zhang, Yunqing Li. [MRA-SNet: Siamese Networks of Multiscale Residual and Attention for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs13224528). 2021. DOI: 10.3390/rs13224528

30. qinao hu. [Layer-contrast foundation representations for pseudo-change suppression in remote sensing change detection](https://doi.org/10.2139/ssrn.7312323). 2026. DOI: 10.2139/ssrn.7312323

31. Jingyi Cao, Yanan You, Yuanyong Ning, Wenli Zhou. [Change Detection Network of Nearshore Ships for Multi-Temporal Optical Remote Sensing Images](https://doi.org/10.1109/igarss39084.2020.9323388). 2020. DOI: 10.1109/igarss39084.2020.9323388

32. xianran zhang, Zhengpeng Li, Jiansheng Wu. [FMT: Foundation Model-based Transformer for Remote Sensing Change Detection](https://doi.org/10.21203/rs.3.rs-7112910/v1). 2025. DOI: 10.21203/rs.3.rs-7112910/v1

33. Zhanlong Chen, Rui Wang, Yongyang Xu. [Semi-Supervised Remote Sensing Building Change Detection with Joint Perturbation and Feature Complementation](https://doi.org/10.3390/rs16183424). 2024. DOI: 10.3390/rs16183424

34. Tee-Ann Teo, Pei-Cheng Chen. [Building Change Detection in Aerial Imagery Using End-to-End Deep Learning Semantic Segmentation Techniques](https://doi.org/10.3390/buildings15050695). 2025. DOI: 10.3390/buildings15050695

35. . [BIT-2103.00208.pdf](fixtures/BIT-2103.00208.pdf). 年份未标明.

36. Kaiqiang Song, Fengzhi Cui, Jie Jiang. [An Efficient Lightweight Neural Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs13245152). 2021. DOI: 10.3390/rs13245152

37. Haoxuan Sun, Xiaogang Yang, Ruitao Lu, Jing Zhang et al.. [MSRNet: Mamba-Based Self-Refinement Framework for Remote Sensing Change Detection](https://doi.org/10.3390/rs18071042). 2026. DOI: 10.3390/rs18071042

38. Mohammad Jabbarizadegan, Piero Fraternali. [Change Detection in Remote Sensing Imagery: A Systematic Review of Statistical, Machine Learning, and Deep Learning Methods](https://doi.org/10.3390/rs18152573). 2026. DOI: 10.3390/rs18152573

39. Wen Lu, Minh Nguyen. [Sliding-Window Dissimilarity Cross-Attention for Near-Real-Time Building Change Detection](https://doi.org/10.3390/rs17010135). 2025. DOI: 10.3390/rs17010135

40. Hongzhu Wang, Zhaoyi Ye, Chuan Xu, Liye Mei et al.. [TTMGNet: Tree Topology Mamba-Guided Network Collaborative Hierarchical Incremental Aggregation for Change Detection](https://doi.org/10.3390/rs16214068). 2024. DOI: 10.3390/rs16214068

41. Feixiang Liu, Yihan Wen, Jiayi Sun, Peipei Zhu et al.. [Iterative Mamba Diffusion Change-Detection Model for Remote Sensing](https://doi.org/10.3390/rs16193651). 2024. DOI: 10.3390/rs16193651

42. Xueqiang Zhao, Zheng Wu, Yangbo Chen, Wei Zhou et al.. [Fine-Grained High-Resolution Remote Sensing Image Change Detection by SAM-UNet Change Detection Model](https://doi.org/10.3390/rs16193620). 2024. DOI: 10.3390/rs16193620

43. José A. Padrón-Hidalgo, Valero Laparra, Nathan Longbotham, Gustau Camps-Valls. [Kernel Anomalous Change Detection for Remote Sensing Imagery](https://doi.org/10.1109/tgrs.2019.2916212). 2020. DOI: 10.1109/tgrs.2019.2916212

44. Jiaxin Song, Shuwen Yang, Yikun Li, Xiaojun Li. [An Unsupervised Remote Sensing Image Change Detection Method Based on RVMamba and Posterior Probability Space Change Vector](https://doi.org/10.3390/rs16244656). 2024. DOI: 10.3390/rs16244656

45. Guanghui Wang, Bin Li, Tao Zhang, Shubi Zhang. [A Network Combining a Transformer and a Convolutional Neural Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs14092228). 2022. DOI: 10.3390/rs14092228

46. Zhiqi Huang, Hongjian You. [MFSFNet: Multi-Scale Feature Subtraction Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs15153740). 2023. DOI: 10.3390/rs15153740

47. Shenbo Liu, Dongxue Zhao, Lijun Tang. [A Multi-Scale Remote Sensing Image Change Detection Network Based on Vision Foundation Model](https://doi.org/10.3390/rs18030506). 2026. DOI: 10.3390/rs18030506

48. Grayson R. Morgan, Cuizhen Wang, Zhenlong Li, Steven R. Schill et al.. [Deep Learning of High-Resolution Aerial Imagery for Coastal Marsh Change Detection: A Comparative Study](https://doi.org/10.20944/preprints202112.0077.v1). 2021. DOI: 10.20944/preprints202112.0077.v1

49. Jiawei Xiong, Feng Liu, Xingyuan Wang, Chaozhong Yang. [Siamese Transformer-Based Building Change Detection in Remote Sensing Images](https://doi.org/10.3390/s24041268). 2024. DOI: 10.3390/s24041268

50. Shanshan Jiang, Haifeng Lin, Hongjin Ren, Ziwei Hu et al.. [MDANet: A High-Resolution City Change Detection Network Based on Difference and Attention Mechanisms under Multi-Scale Feature Fusion](https://doi.org/10.3390/rs16081387). 2024. DOI: 10.3390/rs16081387

51. Wele Gedara Chaminda Bandara, Vishal M. Patel. [Revisiting Consistency Regularization for Semi-supervised Change Detection in Remote Sensing Images](https://arxiv.org/abs/2204.08454). 2022.

52. Hayder Mosa Merza, Ihab Sbeity, Mohamed Dbouk, Zein Al-Abidin Ibrahim. [Building change detection via classification in high-resolution aerial imagery](https://doi.org/10.11591/ijai.v14.i5.pp4319-4331). 2025. DOI: 10.11591/ijai.v14.i5.pp4319-4331

53. Song Cao, Bing Tang, Wei Liang, Yuxiang Chen. [Frequency-aware dual-domain network for remote sensing optical image change detection](https://doi.org/10.1117/1.jrs.20.018504). 2026. DOI: 10.1117/1.jrs.20.018504

54. Bin Li, Guanghui Wang, Tao Zhang, Huachao Yang et al.. [Remote Sensing Image-Change Detection with Pre-Generation of Depthwise-Separable Change-Salient Maps](https://doi.org/10.3390/rs14194972). 2022. DOI: 10.3390/rs14194972

55. Weitong Ma, Fengyan Wang, Chengyao Zhang, Xue Ji et al.. [Island Building Change Detection in High-Resolution Remote Sensing Images Using Hybrid Attention and Cross-Scale Feature Enhancement](https://doi.org/10.2139/ssrn.7218203). 2026. DOI: 10.2139/ssrn.7218203

56. Guowei Lu, Shunyu Yao, Yao Li, Jinbo Tang et al.. [A Semantic-Guided Cross-Attention Network for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs17101749). 2025. DOI: 10.3390/rs17101749

57. Chengyi Li. [Automatic Monitoring of Mines Mining based on Multitemporal Remote Sensing Image Change Detection](https://doi.org/10.5194/egusphere-egu2020-12012). 2020. DOI: 10.5194/egusphere-egu2020-12012

58. You He, Hanchao Zhang, Xiaogang Ning, Ruiqian Zhang et al.. [Spatial-Temporal Semantic Perception Network for Remote Sensing Image Semantic Change Detection](https://doi.org/10.3390/rs15164095). 2023. DOI: 10.3390/rs15164095

59. Zhuo Zheng, Ailong Ma, Liangpei Zhang, Yanfei Zhong. [Change is Everywhere: Single-Temporal Supervised Object Change Detection in Remote Sensing Imagery](https://arxiv.org/abs/2108.07002). 2021.

60. Jiankang Li, Shanyou Zhu, Yiyao Gao, Guixin Zhang et al.. [Change Detection for High-Resolution Remote Sensing Images Based on a Multi-Scale Attention Siamese Network](https://doi.org/10.3390/rs14143464). 2022. DOI: 10.3390/rs14143464

61. Ning Lu, Can Chen, Wenbo Shi, Junwei Zhang et al.. [Weakly Supervised Change Detection Based on Edge Mapping and SDAE Network in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs12233907). 2020. DOI: 10.3390/rs12233907

62. Junyi Zhang, Renwen Chen, Fei Liu, Hao Liu et al.. [DC-Mamba: A Novel Network for Enhanced Remote Sensing Change Detection in Difficult Cases](https://doi.org/10.3390/rs16224186). 2024. DOI: 10.3390/rs16224186

63. Hao Chen, Zhenwei Shi. [A Spatial-Temporal Attention-Based Method and a New Dataset for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs12101662). 2020. DOI: 10.3390/rs12101662

64. Jianli Zhang, Liwei Tao, Wenbo Wei, Pengfei Ma et al.. [CMSNet: A SAM-Enhanced CNN–Mamba Framework for Damaged Building Change Detection in Remote Sensing Imagery](https://doi.org/10.3390/rs17233913). 2025. DOI: 10.3390/rs17233913

65. Daifeng Peng, Min Liu, Haiyan Guan. [Perturbation Matters: A Novel Approach for Semi-Supervised Remote Sensing Imagery Change Detection](https://doi.org/10.3390/rs17040576). 2025. DOI: 10.3390/rs17040576

66. qinao hu. [Pseudo-change suppression for remote sensing change detection via intermediate foundation features](https://doi.org/10.2139/ssrn.7230761). 2026. DOI: 10.2139/ssrn.7230761

67. Lazhar Khelifi, Max Mignotte. [Deep Learning for Change Detection in Remote Sensing Images: Comprehensive Review and Meta-Analysis](https://arxiv.org/abs/2006.05612). 2020.

68. Ying Zha, Mengmeng Li, Xuanguang Liu. [Incorporating Directional Relationship Modelling for Building Change Detection from Very-High-Resolution Satellite Images](https://doi.org/10.14358/pers.25-00114r2). 2026. DOI: 10.14358/pers.25-00114r2

69. Oliver Sefrin, Felix M. Riese, Sina Keller. [Deep Learning for Land Cover Change Detection](https://doi.org/10.3390/rs13010078). 2020. DOI: 10.3390/rs13010078

70. Junyao Kuang, Hongwei Ge. [2DMCG: 2D mamba with change flow guidance for change detection in remote sensing](https://doi.org/10.1177/1088467x251401374). 2025. DOI: 10.1177/1088467x251401374

71. Tianyu Yan, Zifu Wan, Pingping Zhang, Gong Cheng et al.. [TransY-Net: Learning Fully Transformer Networks for Change Detection of Remote Sensing Images](https://doi.org/10.1109/tgrs.2023.3327253). 2023. DOI: 10.1109/tgrs.2023.3327253

72. Yuxing Chen, Lorenzo Bruzzone. [Self-Supervised Change Detection in Multiview Remote Sensing Images](https://doi.org/10.1109/tgrs.2021.3089453). 2022. DOI: 10.1109/tgrs.2021.3089453

73. Le Yang, Yiming Chen, Shiji Song, Fan Li et al.. [Deep Siamese Networks Based Change Detection with Remote Sensing Images](https://doi.org/10.3390/rs13173394). 2021. DOI: 10.3390/rs13173394

74. Bo Jiang, Zitian Wang, Xixi Wang, Ziyan Zhang et al.. [VcT: Visual Change Transformer for Remote Sensing Image Change Detection](https://doi.org/10.1109/tgrs.2023.3327139). 2023. DOI: 10.1109/tgrs.2023.3327139

75. Kaiqiang Song, Jie Jiang. [AGCDetNet:An Attention-Guided Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.1109/jstars.2021.3077545). 2021. DOI: 10.1109/jstars.2021.3077545

76. Junhao Qian, Min Xia, Yonghong Zhang, Jia Liu et al.. [TCDNet: Trilateral Change Detection Network for Google Earth Image](https://doi.org/10.3390/rs12172669). 2020. DOI: 10.3390/rs12172669

77. Weiming Li, Lihui Xue, Xueqian Wang, Gang Li. [MCTNet: A Multi-Scale CNN-Transformer Network for Change Detection in Optical Remote Sensing Images](https://doi.org/10.23919/fusion52260.2023.10224182). 2022. DOI: 10.23919/fusion52260.2023.10224182

78. Jiaxiang Zheng, Yichen Tian, Chao Yuan, Kai Yin et al.. [MDESNet: Multitask Difference-Enhanced Siamese Network for Building Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs14153775). 2022. DOI: 10.3390/rs14153775

79. Yi Zhang, Lei Fu, Ying Li, Yanning Zhang. [HDFNet: Hierarchical Dynamic Fusion Network for Change Detection in Optical Aerial Images](https://doi.org/10.3390/rs13081440). 2021. DOI: 10.3390/rs13081440

80. Shailendra Dabral, Anam Sabir, Unmesh Khati. [MS-HySAN: A Hybrid Multi-Scale Siamese Attention Network for Interpretable Change Detection in High-Resolution Satellite Imagery](https://doi.org/10.20944/preprints202605.1851.v1). 2026. DOI: 10.20944/preprints202605.1851.v1

81. Xuwei Xu, Yuan Zhou, Xiechun Lu, Zhanlong Chen. [FERA-Net: A Building Change Detection Method for High-Resolution Remote Sensing Imagery Based on Residual Attention and High-Frequency Features](https://doi.org/10.3390/rs15020395). 2023. DOI: 10.3390/rs15020395

82. Mehdi Khoshboresh-Masouleh, Reza Shah-Hosseini. [Deep few-shot learning for bi-temporal building change detection](https://arxiv.org/abs/2108.11262). 2021.

83. Hongyang Yin, Chong Ma, Liguo Weng, Min Xia et al.. [Bitemporal Remote Sensing Image Change Detection Network Based on Siamese-Attention Feedback Architecture](https://doi.org/10.3390/rs15174186). 2023. DOI: 10.3390/rs15174186

84. Dalong Zheng, Zhihui Wei, Zebin Wu, Jia Liu. [Learning Pairwise Potential CRFs in Deep Siamese Network for Change Detection](https://doi.org/10.3390/rs14040841). 2022. DOI: 10.3390/rs14040841

85. Wengzheng Wu, Shengyan Liu, Kaibo Qin, Yinuo Wang et al.. [PCINet: A Prior-Guided Correlation Interaction Network for High-Resolution Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18152491). 2026. DOI: 10.3390/rs18152491

86. Xiangrong Zhang, Ling He, Kai Qin, Qi Dang et al.. [SMD-Net: Siamese Multi-Scale Difference-Enhancement Network for Change Detection in Remote Sensing](https://doi.org/10.3390/rs14071580). 2022. DOI: 10.3390/rs14071580

87. Gang Wei, Yuqi Miao, Zhicheng Wang. [Siamese-SAM: Remote Sensing Image Change Detection with Siamese Structure Segment Anything Model](https://doi.org/10.3390/app15073475). 2025. DOI: 10.3390/app15073475

88. Chengzhe Sun, Jiangjiang Wu, Hao Chen, Chun Du. [SemiSANet: A Semi-Supervised High-Resolution Remote Sensing Image Change Detection Model Using Siamese Networks with Graph Attention](https://doi.org/10.3390/rs14122801). 2022. DOI: 10.3390/rs14122801

89. Enze Zhang, Yan Li, Haifeng Lin, Min Xia. [A Lightweight Remote-Sensing Image-Change Detection Algorithm Based on Asymmetric Convolution and Attention Coupling](https://doi.org/10.3390/rs17132226). 2025. DOI: 10.3390/rs17132226

90. Yukun Wang, Mengmeng Wang, Zhonghu Hao, Qiang Wang et al.. [MSGFNet: Multi-Scale Gated Fusion Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs16030572). 2024. DOI: 10.3390/rs16030572

91. Meng Zhou, Weixian Qian, Kan Ren. [Multistage Interaction Network for Remote Sensing Change Detection](https://doi.org/10.3390/rs16061077). 2024. DOI: 10.3390/rs16061077

92. Qing Ding, Zhenfeng Shao, Xiao Huang, Orhan Altan. [DSA-Net: A novel deeply supervised attention-guided network for building change detection in high-resolution remote sensing images](https://doi.org/10.1016/j.jag.2021.102591). 2021. DOI: 10.1016/j.jag.2021.102591

93. Tianyu Yan, Zifu Wan, Pingping Zhang. [Fully Transformer Network for Change Detection of Remote Sensing Images](https://arxiv.org/abs/2210.00757). 2022.

94. Zhinan Cai, Zhiyu Jiang, Yuan Yuan. [Task-Related Self-Supervised Learning For Remote Sensing Image Change Detection](https://doi.org/10.1109/icassp39728.2021.9414387). 2021. DOI: 10.1109/icassp39728.2021.9414387

95. Chong Ma, Hongyang Yin, Liguo Weng, Min Xia et al.. [DAFNet: A Novel Change-Detection Model for High-Resolution Remote-Sensing Imagery Based on Feature Difference and Attention Mechanism](https://doi.org/10.3390/rs15153896). 2023. DOI: 10.3390/rs15153896

96. Moyang Wang, Kun Tan, Xiuping Jia, Xue Wang et al.. [A Deep Siamese Network with Hybrid Convolutional Feature Extraction Module for Change Detection Based on Multi-sensor Remote Sensing Images](https://doi.org/10.3390/rs12020205). 2020. DOI: 10.3390/rs12020205

97. Song Peng, Jing Li, Tian Zhang. [SAM-FDN: A SAM Fine-Tuning Adaptation Remote Sensing Change Detection Method Based on Fourier Frequency Domain Analysis Difference Reinforcement](https://doi.org/10.3390/rs17233842). 2025. DOI: 10.3390/rs17233842

98. Yingying Liu, Gang Zhou. [Laddering vision foundation model for remote sensing image change detection](https://doi.org/10.1117/1.jrs.18.036503). 2024. DOI: 10.1117/1.jrs.18.036503

99. Weikang Yu, Xiaokang Zhang, Richard Gloaguen, Xiao Xiang Zhu et al.. [MineNetCD: A Benchmark for Global Mining Change Detection on Remote Sensing Imagery](https://doi.org/10.1109/tgrs.2024.3491715). 2024. DOI: 10.1109/tgrs.2024.3491715

100. Mingxuan Ding, Qirong Zhou, Qiaolin Ye, Le Sun. [Locally Adaptive Mamba and Multi-Scale Feature Enhancement for Optical Remote Sensing Image Change Detection](https://doi.org/10.3390/rs18132226). 2026. DOI: 10.3390/rs18132226

101. Dongxu Li, Peng Chu, Chen Yang, Zhen Wang et al.. [ATCFNet: A Lightweight Cross-Level Attention-Guided High-Resolution Remote Sensing Image Change Detection Network](https://doi.org/10.3390/rs18091306). 2026. DOI: 10.3390/rs18091306

102. Valerio Marsocci, Virginia Coletta, Roberta Ravanelli, Simone Scardapane et al.. [Inferring 3D change detection from bitemporal optical images](https://arxiv.org/abs/2205.15903). 2022.

103. Yuan Zhou, Xiangrui Li. [Unsupervised Self-training Algorithm Based on Deep Learning for Optical Aerial Images Change Detection](https://arxiv.org/abs/2010.07469). 2020.

104. Zan Mao, Xinyu Tong, Ze Luo, Honghai Zhang. [MFATNet: Multi-Scale Feature Aggregation via Transformer for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs14215379). 2022. DOI: 10.3390/rs14215379

105. Ebrahim Ghaderpour, Tijana Vujadinovic. [Change Detection within Remotely Sensed Satellite Image Time Series via Spectral Analysis](https://doi.org/10.3390/rs12234001). 2020. DOI: 10.3390/rs12234001

106. Yue Wu, Zhuangfei Bai, Qiguang Miao, Wenping Ma et al.. [A Classified Adversarial Network for Multi-Spectral Remote Sensing Image Change Detection](https://doi.org/10.3390/rs12132098). 2020. DOI: 10.3390/rs12132098

107. Dehao Wang, Liguo Weng, Min Xia, Haifeng Lin. [MBCNet: Multi-Branch Collaborative Change-Detection Network Based on Siamese Structure](https://doi.org/10.3390/rs15092237). 2023. DOI: 10.3390/rs15092237

108. Hongruixuan Chen, Jian Song, Naoto Yokoya. [Change Detection between Optical Remote Sensing Imagery and Map Data Via Segment Anything Model (SAM)](https://doi.org/10.1109/igarss53475.2024.10642789). 2024. DOI: 10.1109/igarss53475.2024.10642789

109. Jinming Wu, Chunhui Xie, Zuxi Zhang, Yongxin Zhu. [A Deeply Supervised Attentive High-Resolution Network for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs15010045). 2022. DOI: 10.3390/rs15010045

110. Ayesha Shafique, Guo Cao, Zia Khan, Muhammad Asad et al.. [Deep Learning-Based Change Detection in Remote Sensing Images: A Review](https://doi.org/10.3390/rs14040871). 2022. DOI: 10.3390/rs14040871

111. Chen Chen, Hongxiang Ma, Guorun Yao, Ning Lv et al.. [Remote Sensing Image Augmentation Based on Text Description for Waterside Change Detection](https://doi.org/10.3390/rs13101894). 2021. DOI: 10.3390/rs13101894

112. Jing Shen, Chunlei Huo, Shiming Xiang. [Siamese InternImage for Change Detection](https://doi.org/10.3390/rs16193642). 2024. DOI: 10.3390/rs16193642

113. Qing Wang, Mengqi Li, Gongquan Li, Jiling Zhang et al.. [High-Resolution Remote Sensing Image Change Detection Method Based on Improved Siamese U-Net](https://doi.org/10.3390/rs15143517). 2023. DOI: 10.3390/rs15143517

114. Yunhe Teng, Shuo Liu, Weichao Sun, Huan Yang et al.. [A VHR Bi-Temporal Remote-Sensing Image Change Detection Network Based on Swin Transformer](https://doi.org/10.3390/rs15102645). 2023. DOI: 10.3390/rs15102645

115. Bo Si, Baiyu Dong, Ke Wang. [A Differential-Based Siamese Network Integrating the CSWin Transformer for Rural Land Cover Semantic Change Detection](https://doi.org/10.3390/rs18040557). 2026. DOI: 10.3390/rs18040557

116. Mengmeng Yin, Zhibo Chen, Chengjian Zhang. [A CNN-Transformer Network Combining CBAM for Change Detection in High-Resolution Remote Sensing Images](https://doi.org/10.3390/rs15092406). 2023. DOI: 10.3390/rs15092406

117. Liwei Qin, Quan Zou, Guoqing Li, Wenyang Yu et al.. [MSMCD: A Multi-Stage Mamba Network for Geohazard Change Detection](https://doi.org/10.3390/rs18010108). 2025. DOI: 10.3390/rs18010108

118. Xueli Peng, Ruofei Zhong, Zhen Li, Qingyang Li. [Optical Remote Sensing Image Change Detection Based on Attention Mechanism and Image Difference](https://doi.org/10.1109/tgrs.2020.3033009). 2021. DOI: 10.1109/tgrs.2020.3033009

119. Quanfu Xu, Keming Chen, Guangyao Zhou, Xian Sun. [Change Capsule Network for Optical Remote Sensing Image Change Detection](https://doi.org/10.3390/rs13142646). 2021. DOI: 10.3390/rs13142646

120. Min Chen, Qiangjiang Zhang, Xuming Ge, Bo Xu et al.. [A Full-Scale Connected CNN–Transformer Network for Remote Sensing Image Change Detection](https://doi.org/10.3390/rs15225383). 2023. DOI: 10.3390/rs15225383

121. Xiao Han, Fanghan Yang, Jieqiong Du, Xiangrong Zhang et al.. [Cross-Image Feature Interaction Network for Change Detection in Remote Sensing Images](https://doi.org/10.3390/rs18050717). 2026. DOI: 10.3390/rs18050717