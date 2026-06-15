package com.studybridge.api.service;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.dto.ArchiveListDTO;
import com.studybridge.api.dto.FolderDTO;
import com.studybridge.api.entity.Folder;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.FolderRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class MaterialService {

    private final MaterialRepository materialRepository;
    private final S3Service s3Service;
    private final PdfExtractionService pdfExtractionService;
    private final MaterialFeedbackRepository materialFeedbackRepository;
    private final MaterialSummaryRepository materialSummaryRepository;
    private final FolderRepository folderRepository;
    private final StudyNoteAnalysisService studyNoteAnalysisService;

    @Transactional
    public MaterialDTO uploadAndSaveMaterial(Long userId, String title, MaterialType type, String keywords,
            org.springframework.web.multipart.MultipartFile file, Long folderId) throws java.io.IOException {
        // 자료보관함에서는 오답노트(REVIEW_NOTE) 유형 생성을 금지한다. (REVIEW_NOTE는 ReviewNoteService가 퀴즈 기반으로만 생성)
        // 프론트에서 라디오를 막아도 API 직접 호출(type=REVIEW_NOTE)을 차단하기 위함. → 400, S3 업로드 전에 거부.
        if (type == MaterialType.REVIEW_NOTE) {
            throw new IllegalArgumentException("자료보관함에서는 오답노트 자료 유형을 생성할 수 없습니다. 오답노트는 별도 오답노트 메뉴에서 관리됩니다.");
        }

        // 업로드 형식 검증: PDF/DOCX만 허용. Content-Type만 믿지 않고 확장자도 함께 확인한다.
        validateUploadFormat(file);

        // 업로드 위치(폴더) 검증: 지정 시 본인 소유 폴더여야 한다. null 이면 루트.
        Long resolvedFolderId = resolveOwnedFolderId(userId, folderId);

        // S3에 파일 업로드
        String s3Key = s3Service.uploadFile(file, userId);

        // DB에 데이터 저장
        Material material = Material.builder()
                .userId(userId)
                .title(title)
                .materialType(type)
                .keywords(keywords)
                .folderId(resolvedFolderId)
                .originalFileName(file.getOriginalFilename())
                .storedFileName(s3Key)
                .s3FileUrl(s3Key)
                .fileSize(file.getSize())
                .extractionStatus(ExtractionStatus.PENDING)
                .build();

        Material savedMaterial = materialRepository.save(material);

        // AI 핵심 요약 노트(전공 분야·핵심 객체 중심) PENDING 행 생성 — 분석은 추출 성공 후 백그라운드.
        try { studyNoteAnalysisService.initPending(savedMaterial); }
        catch (Exception e) { log.warn("학습 노트 PENDING 초기화 실패 materialId={}: {}", savedMaterial.getMaterialId(), e.getMessage()); }

        // FastAPI로 텍스트 추출
        pdfExtractionService.sendToFastApiForExtraction(
                savedMaterial.getMaterialId(),
                file.getBytes(),
                file.getOriginalFilename(),
                file.getContentType());

        return convertToDTO(savedMaterial);
    }

    // PDF / DOCX만 허용. 구형 .doc는 친화 메시지로 거부. Content-Type + 확장자 동시 확인.
    private void validateUploadFormat(org.springframework.web.multipart.MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("업로드할 파일이 비어 있습니다.");
        }
        final String PDF = "application/pdf";
        final String DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

        String name = file.getOriginalFilename() != null ? file.getOriginalFilename().toLowerCase() : "";
        String contentType = file.getContentType() != null ? file.getContentType().toLowerCase() : "";

        // 구형 .doc는 명시적으로 거부하고 변환 안내를 준다.
        if (name.endsWith(".doc") && !name.endsWith(".docx")) {
            throw new IllegalArgumentException("현재는 .docx 형식만 지원합니다. .doc 파일은 .docx로 변환 후 업로드해주세요.");
        }

        boolean extOk = name.endsWith(".pdf") || name.endsWith(".docx");
        boolean typeOk = contentType.equals(PDF) || contentType.equals(DOCX)
                // 일부 브라우저/OS는 docx에 빈/일반 content-type을 보낼 수 있어 확장자가 맞으면 허용
                || contentType.isBlank() || contentType.equals("application/octet-stream");

        if (!extOk || !typeOk) {
            throw new IllegalArgumentException("지원하지 않는 파일 형식입니다. PDF 또는 DOCX 파일만 업로드할 수 있습니다.");
        }
    }

    @Transactional
    public MaterialDTO saveStudyLog(Long userId, String title, String keywords, java.time.LocalDate studyDate,
            String learningContent, String nextPlan, Long folderId) {
        Material material = Material.builder()
                .userId(userId)
                .title(title)
                .materialType(MaterialType.STUDY_LOG)
                .keywords(keywords)
                .folderId(resolveOwnedFolderId(userId, folderId))
                .studyDate(studyDate)
                .learningContent(learningContent)
                .nextPlan(nextPlan)
                .fileSize(0L)
                .extractionStatus(ExtractionStatus.SUCCESS) // 텍스트만 있으므로 추출 성공(완료)으로 간주
                .build();

        Material savedMaterial = materialRepository.save(material);
        return convertToDTO(savedMaterial);
    }

    @Transactional
    public MaterialDTO updateMaterial(Long userId, Long materialId, MaterialDTO.UpdateRequest request) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 수정 권한이 없습니다.");
        }

        if (request.getTitle() != null && !request.getTitle().isBlank()) {
            material.setTitle(request.getTitle());
        }
        if (request.getKeywords() != null) {
            material.setKeywords(request.getKeywords());
        }
        
        // 학습일지인 경우 학습 내용 및 계획 업데이트
        if (material.getMaterialType() == MaterialType.STUDY_LOG) {
            boolean contentChanged = false;
            
            if (request.getLearningContent() != null && !request.getLearningContent().equals(material.getLearningContent())) {
                material.setLearningContent(request.getLearningContent());
                contentChanged = true;
            }
            if (request.getNextPlan() != null && !request.getNextPlan().equals(material.getNextPlan())) {
                material.setNextPlan(request.getNextPlan());
                contentChanged = true;
            }
            
            // 학습 내용이 변경되었다면, 기존에 생성된 AI 피드백 및 요약 데이터를 삭제하여 다음에 다시 생성되도록 함
            if (contentChanged) {
                materialFeedbackRepository.findByMaterial_MaterialId(materialId)
                        .ifPresent(fb -> {
                            material.setFeedback(null);
                            materialFeedbackRepository.delete(fb);
                        });
                materialSummaryRepository.findByMaterial_MaterialId(materialId)
                        .ifPresent(sm -> {
                            material.setSummary(null);
                            materialSummaryRepository.delete(sm);
                        });
                materialRepository.saveAndFlush(material); // 강제 동기화
            }
        }

        return convertToDTO(material);
    }

    @Transactional
    public void deleteMaterial(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 삭제 권한이 없습니다.");
        }

        // S3에서 삭제
        if (material.getMaterialType() != MaterialType.STUDY_LOG && material.getStoredFileName() != null) {
            s3Service.deleteFile(material.getStoredFileName());
        }

        materialRepository.delete(material);
    }

    public List<MaterialDTO> getUserMaterials(Long userId) {
        return materialRepository.findByUserIdOrderByUploadedAtDesc(userId).stream()
                // 자료보관함 목록에서 오답노트(REVIEW_NOTE)는 제외한다. 오답노트는 별도 /api/review-notes 로만 노출.
                .filter(material -> material.getMaterialType() != MaterialType.REVIEW_NOTE)
                .map(material -> {
                    try {
                        return convertToDTO(material);
                    } catch (Exception e) {
                        // S3 또는 기타 오류가 개별 자료에서 발생해도 목록 전체를 실패시키지 않는다
                        log.warn("getUserMaterials: convertToDTO failed for materialId={} err={}", material.getMaterialId(), e.getMessage());
                        return convertToDTOWithoutS3(material);
                    }
                })
                .collect(Collectors.toList());
    }

    /** 폴더 id 검증: null 이면 그대로 루트, 아니면 본인 소유 폴더인지 확인 후 반환. */
    private Long resolveOwnedFolderId(Long userId, Long folderId) {
        if (folderId == null) return null;
        Folder folder = folderRepository.findById(folderId)
                .orElseThrow(() -> new IllegalArgumentException("폴더를 찾을 수 없습니다."));
        if (!folder.getUserId().equals(userId)) {
            throw new SecurityException("해당 폴더에 대한 권한이 없습니다.");
        }
        return folderId;
    }

    /** 자료보관함 폴더 뷰 한 화면 조회(현재 위치의 하위 폴더 + 자료 + breadcrumb). parentId=null 이면 루트. */
    public ArchiveListDTO getArchiveItems(Long userId, Long parentId) {
        resolveOwnedFolderId(userId, parentId); // 위치 소유/존재 검증

        List<FolderDTO> folders = (parentId == null
                ? folderRepository.findByUserIdAndParentIdIsNullOrderByCreatedAtDesc(userId)
                : folderRepository.findByUserIdAndParentIdOrderByCreatedAtDesc(userId, parentId))
                .stream().map(FolderDTO::from).collect(Collectors.toList());

        List<Material> rawMaterials = (parentId == null
                ? materialRepository.findByUserIdAndFolderIdIsNullOrderByUploadedAtDesc(userId)
                : materialRepository.findByUserIdAndFolderIdOrderByUploadedAtDesc(userId, parentId));

        List<MaterialDTO> materials = rawMaterials.stream()
                .filter(m -> m.getMaterialType() != MaterialType.REVIEW_NOTE)
                .map(m -> {
                    try { return convertToDTO(m); }
                    catch (Exception e) {
                        log.warn("getArchiveItems: convertToDTO failed for materialId={} err={}", m.getMaterialId(), e.getMessage());
                        return convertToDTOWithoutS3(m);
                    }
                })
                .collect(Collectors.toList());

        // breadcrumb: 현재 폴더 → 루트로 거슬러 올라간 뒤 뒤집어 루트→현재 순
        List<FolderDTO> breadcrumb = new java.util.ArrayList<>();
        Long cursor = parentId;
        int guard = 0;
        while (cursor != null && guard++ < 1000) {
            Folder f = folderRepository.findById(cursor).orElse(null);
            if (f == null || !f.getUserId().equals(userId)) break;
            breadcrumb.add(FolderDTO.from(f));
            cursor = f.getParentId();
        }
        java.util.Collections.reverse(breadcrumb);

        return ArchiveListDTO.builder()
                .currentFolderId(parentId)
                .breadcrumb(breadcrumb)
                .folders(folders)
                .materials(materials)
                .build();
    }

    /** 자료를 다른 폴더로 이동(folderId=null 이면 루트로). 자료/대상 폴더 모두 본인 소유여야 한다. */
    @Transactional
    public MaterialDTO moveMaterial(Long userId, Long materialId, Long targetFolderId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 권한이 없습니다.");
        }
        material.setFolderId(resolveOwnedFolderId(userId, targetFolderId));
        return convertToDTO(materialRepository.save(material));
    }

    // 자료 상세 조회
    // context="review-note" 인 경우에만 오답노트(REVIEW_NOTE) 상세를 허용한다(전용 복습 화면 ReviewNoteArchiveDetail 진입).
    // 그 외(일반 자료보관함 상세) 경로로 오답노트 materialId가 들어오면 404 로 차단한다.
    public MaterialDTO getMaterial(Long userId, Long materialId, String context) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 조회 권한이 없습니다.");
        }

        if (material.getMaterialType() == MaterialType.REVIEW_NOTE && !"review-note".equals(context)) {
            throw new java.util.NoSuchElementException("오답노트 자료는 자료보관함 상세에서 열 수 없습니다.");
        }

        return convertToDTO(material);
    }

    private MaterialDTO convertToDTO(Material material) {
        String presignedUrl = null;
        if (material.getS3FileUrl() != null && !material.getS3FileUrl().isBlank()) {
            try {
                presignedUrl = s3Service.getPresignedUrl(material.getS3FileUrl(), material.getOriginalFileName());
            } catch (Exception e) {
                // S3 Presigned URL 생성 실패는 해당 자료에만 영향을 줌 (목록 전체 실패 방지)
                log.warn("S3 presignedUrl 생성 실패 materialId={}: {}", material.getMaterialId(), e.getMessage());
            }
        }
        return MaterialDTO.builder()
                .materialId(material.getMaterialId())
                .title(material.getTitle())
                .materialType(material.getMaterialType())
                .keywords(material.getKeywords())
                .folderId(material.getFolderId())
                .studyDate(material.getStudyDate())
                .learningContent(material.getLearningContent())
                .nextPlan(material.getNextPlan())
                .originalFileName(material.getOriginalFileName())
                .fileSize(material.getFileSize())
                .extractionStatus(material.getExtractionStatus())
                .s3PresignedUrl(presignedUrl)
                .uploadedAt(material.getUploadedAt())
                .build();
    }

    // S3 없이 기본 정보만 반환 (fallback)
    private MaterialDTO convertToDTOWithoutS3(Material material) {
        return MaterialDTO.builder()
                .materialId(material.getMaterialId())
                .title(material.getTitle())
                .materialType(material.getMaterialType())
                .keywords(material.getKeywords())
                .folderId(material.getFolderId())
                .studyDate(material.getStudyDate())
                .learningContent(material.getLearningContent())
                .nextPlan(material.getNextPlan())
                .originalFileName(material.getOriginalFileName())
                .fileSize(material.getFileSize())
                .extractionStatus(material.getExtractionStatus())
                .s3PresignedUrl(null)
                .uploadedAt(material.getUploadedAt())
                .build();
    }

    private String generatePresignedUrl(String s3Key) {
        return s3Service.getPresignedUrl(s3Key);
    }
}